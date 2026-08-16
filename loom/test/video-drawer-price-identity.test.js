import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { buildPayload, priceKey, canSubmit, PRICE_KEY_SKIP } from "../../gallery/src/gen/videoDrawerCore.js";

/* THE STALE-FREE RACE (issue #15 follow-up, 2026-08-16). The video drawer's cost badge could hold
   a settled FREE for a 5s payload while the form already said 15s: debCost() only SCHEDULED, and
   setChecking fired 250ms later inside costNow, so for the debounce plus one RTT the badge read
   FREE and Go submitted a 15s payload against a 5s verdict. Worse, the Quality and Camera selects
   mutated the form with NO debCost at all, though both ride the priced payload (i2vPro.mode /
   cameraMovement) -- a settled quote for a DIFFERENT payload with nothing pending to correct it.

   The repair keys the gate on PAYLOAD IDENTITY, not timing: costNow records priceKey(p) of the
   payload it actually priced; canSubmit lets Go through only when a settled verdict exists, no
   re-price is pending, and that verdict's key equals the key of the payload Go would submit now.
   The two helpers are PURE (videoDrawerCore.js) and are driven here through the exact sequences
   that used to spend against the wrong quote; the source-guard block pins the host wiring the
   suite has no React harness to click through. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../gallery/src/components/VideoDrawer.jsx"), "utf8")
  .replace(/\r\n/g, "\n");

function drawer(init) {
  return Object.assign({
    mode: "i2v", slots: [{ media_id: "111", thumb: "t", is_nsfw: false }], imgSlots: [null], vidSlots: [], audSlot: null,
    model: "v4.0.1", duration: 5, camera: "unset", quality: "professional",
    channel: "normal", audioGen: false, audioLanguage: "english", negative: "", modeNote: "",
  }, init);
}

// A minimal stand-in for the host's debCost -> costNow -> settle cycle over the pure state shape.
const scheduled = () => ({ settled: false, pricedKey: null, pendingTimer: true });
const inFlight = () => ({ settled: false, pricedKey: null, pendingTimer: false });
const settledFor = (payload) => ({ settled: true, pricedKey: priceKey(payload), pendingTimer: false });

describe("priceKey: stable identity of the priced payload", () => {
  test("drops ONLY prompt and negative -- every other field is part of the identity", () => {
    assert.deepEqual(PRICE_KEY_SKIP.slice().sort(), ["negative", "prompt"]);
    const d = drawer({});
    const a = priceKey(buildPayload(d, "a slow pan"));
    const b = priceKey(buildPayload(d, "an entirely different prompt"));
    assert.equal(a, b, "prompt text never prices and is edited without a repaint -- it must not move the key");
    assert.equal(priceKey(buildPayload(drawer({ negative: "blurry" }), "")), a, "negative is out of the key too");
    // Every remaining buildPayload field moves the key (the whole i2vPro/referenceVideo block is
    // priced server-side, so over-including is the safe direction).
    const p = buildPayload(d, "");
    Object.keys(p).filter((k) => PRICE_KEY_SKIP.indexOf(k) === -1).forEach((k) => {
      const q = { ...p, [k]: (typeof p[k] === "boolean") ? !p[k] : (Array.isArray(p[k]) ? p[k].concat(["X"]) : String(p[k]) + "X") };
      assert.notEqual(priceKey(q), priceKey(p), "changing " + k + " must change the price key");
    });
  });

  test("is stable across key order (it is an identity, not a serialization accident)", () => {
    const p = buildPayload(drawer({}), "");
    const shuffled = Object.keys(p).reverse().reduce((o, k) => (o[k] = p[k], o), {});
    assert.equal(priceKey(shuffled), priceKey(p));
  });

  test("tolerates junk without throwing (a null payload keys to nothing, never to something)", () => {
    assert.equal(priceKey(null), "");
    assert.equal(priceKey(undefined), "");
    assert.equal(canSubmit(settledFor({ a: 1 }), null), false);
  });
});

describe("canSubmit: the Go gate is payload identity, not timing", () => {
  test("MONEY TRIGGER 15s -> 5s -> 15s: a settled 5s verdict never carries a 15s submit", () => {
    const d = drawer({ duration: 15 });
    let price = settledFor(buildPayload(d, ""));
    assert.equal(canSubmit(price, buildPayload(d, "")), true, "settled for THIS payload -> Go");
    // user picks 5s: the host debounces (scheduled), then fires (in flight), then settles for 5s
    d.duration = 5;
    assert.equal(canSubmit(price, buildPayload(d, "")), false, "the 15s verdict is not the 5s payload's");
    price = scheduled();
    assert.equal(canSubmit(price, buildPayload(d, "")), false);
    price = inFlight();
    assert.equal(canSubmit(price, buildPayload(d, "")), false);
    price = settledFor(buildPayload(d, ""));
    assert.equal(canSubmit(price, buildPayload(d, "")), true, "settled FREE for 5s -> Go on the 5s payload");
    // the race: user flips back to 15s; the badge still says FREE (for 5s) and no timer has fired
    d.duration = 15;
    assert.equal(canSubmit(price, buildPayload(d, "")), false,
      "the badge's settled FREE is for the 5s payload -- a 15s submit against it is the stale-FREE spend");
    price = scheduled();
    assert.equal(canSubmit(price, buildPayload(d, "")), false, "a pending re-price disables Go outright");
  });

  test("quality change with NO re-price: the settled key no longer matches, Go is off", () => {
    const d = drawer({ quality: "professional" });
    const price = settledFor(buildPayload(d, ""));
    d.quality = "basic";   // the old Quality onChange mutated exactly this and scheduled nothing
    assert.equal(canSubmit(price, buildPayload(d, "")), false,
      "i2vPro.mode rides the priced payload -- a professional quote must not carry a basic submit (or vice versa)");
    d.quality = "professional";
    assert.equal(canSubmit(price, buildPayload(d, "")), true, "restoring the priced value restores the match");
  });

  test("camera change with NO re-price: same story (i2vPro.cameraMovement is priced)", () => {
    const d = drawer({ camera: "unset" });
    const price = settledFor(buildPayload(d, ""));
    d.camera = "zoom";
    assert.equal(canSubmit(price, buildPayload(d, "")), false);
  });

  test("a pending timer disables Go even when the settled key would match", () => {
    const d = drawer({});
    const p = buildPayload(d, "");
    // an in-flight answer for the SAME payload can settle while a re-price is still scheduled --
    // pendingTimer alone must veto (whatever is on the badge is known-stale by definition).
    assert.equal(canSubmit({ settled: true, pricedKey: priceKey(p), pendingTimer: true }, p), false);
    assert.equal(canSubmit({ settled: true, pricedKey: priceKey(p), pendingTimer: false }, p), true);
  });

  test("a stale key (settled for some other payload) is refused; unsettled and null keys are refused", () => {
    const d = drawer({});
    const p = buildPayload(d, "");
    assert.equal(canSubmit({ settled: true, pricedKey: "not-this-payload", pendingTimer: false }, p), false);
    assert.equal(canSubmit({ settled: true, pricedKey: null, pendingTimer: false }, p), false);
    assert.equal(canSubmit({ settled: false, pricedKey: priceKey(p), pendingTimer: false }, p), false);
    assert.equal(canSubmit(null, p), false);
    assert.equal(canSubmit(undefined, p), false);
  });

  test("prompt edits alone do not break the match (prompt never prices; the ce edits without a repaint)", () => {
    const d = drawer({});
    const price = settledFor(buildPayload(d, "first draft"));
    assert.equal(canSubmit(price, buildPayload(d, "second draft, much longer")), true);
  });
});

/* ---- source guards on the host wiring (no React harness in this suite) ---- */

function fnBody(name) {
  // Accept any parameter list -- debCost grew a `force` flag; a signature change must not
  // silently turn these guards into a false pass/fail.
  const m = new RegExp("const " + name + " = \\([^)]*\\) => \\{").exec(src);
  assert.ok(m, "expected to find " + name + "(...) in VideoDrawer.jsx");
  const i = m.index;
  const end = src.indexOf("\n  };", i);   // component-level 2-space indent closes it
  return src.slice(i, end);
}

describe("<VideoDrawer> host wiring of the price identity gate", () => {
  test("debCost() blanks the badge SYNCHRONOUSLY, before scheduling -- and drops the verdict identity", () => {
    const body = fnBody("debCost");
    const check = body.indexOf("setChecking()");
    const sched = body.indexOf("setTimeout(costNow");
    assert.ok(check >= 0, "debCost must call setChecking() itself (mirror useGenerate's refreshPrice)");
    assert.ok(sched >= 0, "debCost must still schedule costNow");
    assert.ok(check < sched, "setChecking() must run BEFORE the setTimeout -- 250ms of stale FREE was the bug");
    assert.match(body, /settled:\s*false/, "debCost must un-settle the verdict");
    assert.match(body, /pendingTimer:\s*true/, "debCost must mark the re-price pending");
    assert.match(body, /costSeq\.current\+\+/, "debCost must invalidate any answer already in flight");
  });

  test("debCost() SHORT-CIRCUITS when the priced payload is unchanged, unless forced (post-submit)", () => {
    // Review 2026-08-16: prompt/negative are outside priceKey ('never prices') yet their handlers
    // call debCost, so every typing pause blanked the badge, disabled Go and re-POSTed /api/price
    // for a byte-identical payload. Fixed at the mechanism: an unchanged settled key returns
    // early. `force` exists for the ONE case where the payload is identical but the verdict is
    // stale anyway -- right after a submit debited the tickets -- so that re-price is not swallowed.
    const body = fnBody("debCost");
    assert.match(body, /const debCost = \(force\) =>/, "debCost takes a `force` flag");
    assert.match(body, /!force && pr && pr\.settled && pr\.pricedKey != null && !pr\.pendingTimer[\s\S]{0,120}pr\.pricedKey === priceKey\(buildPayload\(st\.current, ""\)\)/,
      "the short-circuit compares the SETTLED key against the current payload's priceKey and is bypassed by force");
    const sc = body.indexOf("if (!force &&");
    const check = body.indexOf("setChecking()");
    assert.ok(sc >= 0 && check >= 0 && sc < check, "the short-circuit must come BEFORE setChecking()");
  });

  test("doGenerate() re-prices (FORCED) right after a successful submit -- the balance changed, the payload did not", () => {
    // Review 2026-08-16, the most serious finding: nothing re-priced after the drawer's own submit
    // consumed the tickets, so a settled FREE for the unchanged payload passed canSubmit and a
    // second click submitted under a FREE badge for a clip the server now found SHORT and charged
    // in full -- the exact #15 shape the identity gate exists to stop.
    const body = fnBody("doGenerate");
    const submit = body.indexOf('emit("mg-submit"');
    const reprice = body.indexOf("debCost(true)");
    assert.ok(submit >= 0, "the success path emits mg-submit");
    assert.ok(reprice >= 0, "the success path must call debCost(true)");
    assert.ok(reprice > submit, "the forced re-price sits in the SUCCESS branch after mg-submit");
  });

  test("costNow() clears pendingTimer BEFORE any early bail, and bounds the fetch with a timeout", () => {
    // Review 2026-08-16: (a) `if (!cost) return` ran before the price-state write, leaving
    // {pendingTimer:true} forever so canSubmit never passed; (b) an unbounded fetch that hung left
    // Go disabled forever on a muted 'Checking cost…' with no error -- fail-silent-closed.
    const body = fnBody("costNow");
    const write = body.indexOf("st.current.price = { settled: false, pricedKey: null, pendingTimer: false }");
    const bail = body.indexOf("if (!cost) return;");
    assert.ok(write >= 0 && bail >= 0 && write < bail, "pendingTimer must be cleared before the no-badge bail");
    assert.match(body, /AbortController/, "the price fetch must be abortable");
    assert.match(body, /PRICE_FETCH_TIMEOUT_MS/, "the abort must use the shared timeout constant");
    assert.match(body, /signal: ctrl \? ctrl\.signal : undefined/, "the fetch must carry the abort signal");
  });

  test("doGenerate() gates the submit on canSubmit() and never silently drops the click", () => {
    const body = fnBody("doGenerate");
    const gate = body.indexOf("canSubmit(");
    const submit = body.indexOf('fetch("/api/loom/generate"');
    assert.ok(gate >= 0, "doGenerate must call canSubmit");
    assert.ok(submit >= 0);
    assert.ok(gate < submit, "the identity gate must sit before the spend");
    const gateBlock = body.slice(gate, submit);
    assert.match(gateBlock, /pushLine\(/, "a refused click must say so (a status line), not vanish");
    assert.match(gateBlock, /debCost\(\)/, "a refused click must kick a re-price");
    assert.match(gateBlock, /return;/);
    // the rendering latch is untouched: it is set only on the path that actually submits
    const latch = body.indexOf("st.current.rendering = true");
    assert.ok(latch > gate && latch < submit, "the busy latch stays between the gate and the submit");
  });

  test("costNow() records the identity only under the costSeq guard, off the payload it priced", () => {
    const body = fnBody("costNow");
    assert.match(body, /const settle = \(key\) => \{ st\.current\.price = \{ settled: true, pricedKey: key, pendingTimer: false \};/);
    const thenIdx = body.indexOf(".then((d) =>");
    assert.ok(thenIdx >= 0);
    const tail = body.slice(thenIdx);
    assert.match(tail, /if \(mine === costSeq\.current && costRef\.current\) \{ costRef\.current\.setPrice\(d\); settle\(priceKey\(p\)\); \}/,
      "the settled response must record priceKey(p) under the seq guard");
    assert.match(tail, /setPrice\(null\); settle\(priceKey\(p\)\);/,
      "a failed check settles too (the red could-not-verify IS this payload's verdict)");
    // the idle exits (nothing to price / flf missing start) are verdicts as well
    assert.match(body, /cost\.clear\(idleHint\); settle\(priceKey\(p\)\); return;/);
  });

  test("canGo reads canSubmit, and Quality + Camera onChange re-price like every other priced field", () => {
    assert.match(src, /const canGo = !s\.hostBusy && !s\.rendering && canSubmit\(s\.price, buildPayload\(s, ""\)\);/);
    const cam = src.match(/className="mgd-sel mgd-cam"[^\n]*onChange=\{\(e\) => \{([^\n]*)\}\}/);
    const qual = src.match(/className="mgd-sel mgd-quality"[^\n]*onChange=\{\(e\) => \{([^\n]*)\}\}/);
    assert.ok(cam && qual, "expected the Camera and Quality selects");
    assert.match(cam[1], /debCost\(\)/, "Camera onChange must debCost -- cameraMovement is priced");
    assert.match(qual[1], /debCost\(\)/, "Quality onChange must debCost -- i2vPro.mode is priced");
  });

  test("every handler that writes a priced form field schedules a re-price", () => {
    // Every `st.current.<field> = ` assignment inside a JSX onChange for a buildPayload input
    // must be followed by debCost() on the same line. imgSlots/vidSlots `.push(null)` adds an
    // EMPTY slot (payload unchanged) and is exempt by construction.
    // `negative` is NOT here on purpose: it is in PRICE_KEY_SKIP ("never prices"), so listing it
    // as priced contradicted priceKey (review 2026-08-16). Its handler may still call debCost --
    // harmlessly, because debCost now short-circuits on an unchanged settled key.
    const priced = ["model", "duration", "camera", "quality", "channel", "audioGen", "audioLanguage", "audSlot"];
    const lines = src.split("\n").filter((l) => /onChange=|onClick=/.test(l));
    priced.forEach((f) => {
      lines.filter((l) => new RegExp("st\\.current\\." + f + " = ").test(l)).forEach((l) => {
        assert.match(l, /debCost\(\)/, "handler writing st.current." + f + " must call debCost(): " + l.trim());
      });
    });
  });

  test("the fields priceKey SKIPS are exactly the ones a keystroke must not un-settle", () => {
    // Guards the contract from both ends: PRICE_KEY_SKIP names prompt/negative, and the drawer's
    // debCost short-circuit is what makes editing them harmless. If someone adds a field to
    // PRICE_KEY_SKIP that a handler writes WITHOUT the short-circuit protecting it, this trips.
    const coreSrc = readFileSync(path.join(__dirname, "../../gallery/src/gen/videoDrawerCore.js"), "utf8");
    assert.match(coreSrc, /export const PRICE_KEY_SKIP = \["prompt", "negative"\];/,
      "PRICE_KEY_SKIP is exactly prompt + negative");
    const body = fnBody("debCost");
    assert.match(body, /if \(!force && pr && pr\.settled/, "debCost's short-circuit protects every non-pricing caller");
  });
});

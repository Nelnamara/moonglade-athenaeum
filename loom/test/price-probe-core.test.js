import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  PRICE_DEBOUNCE_MS, PRICE_FETCH_TIMEOUT_MS, PRICE_KEY_SKIP,
  canSubmit, fired, initialVerdict, priceKey, scheduled, settledFor, shouldShortCircuit,
} from "../../gallery/src/gen/priceProbeCore.js";
import { buildPayload } from "../../gallery/src/gen/videoDrawerCore.js";
import { EDIT_PRICE_KEY_SKIP, buildEditPayload } from "../../gallery/src/gen/editCore.js";

/* THE STALE-FREE RACE (issue #15 follow-up, 2026-08-16) and its generalisation (2026-08-22).
   A cost badge could hold a settled FREE for a 5s payload while the form already said 15s: the
   refresh only SCHEDULED, and setChecking fired 250ms later, so for the debounce plus one RTT
   the badge read FREE and Go submitted a 15s payload against a 5s verdict. Worse, the Quality
   and Camera selects mutated the form with NO re-price at all, though both ride the priced
   payload (i2vPro.mode / cameraMovement) -- a settled quote for a DIFFERENT payload with nothing
   pending to correct it.

   The repair keys the gate on PAYLOAD IDENTITY, not timing: the probe records priceKey(p) of the
   payload it actually priced; canSubmit lets Go through only when a settled verdict exists, no
   re-price is pending, and that verdict's key equals the key of the payload Go would submit now.
   Written for the video drawer alone, it now backs all six cost lines through
   gallery/src/gen/priceProbeCore.js -- so these sequences are driven against the SHARED module.
   (The video-drawer-specific host wiring is pinned in video-drawer-price-identity.test.js; the
   one-module/one-fetch structure in price-probe-structure.test.js.) */

function drawer(init) {
  return Object.assign({
    mode: "i2v", slots: [{ media_id: "111", thumb: "t", is_nsfw: false }], imgSlots: [null], vidSlots: [], audSlot: null,
    model: "v4.0.1", duration: 5, camera: "unset", quality: "professional",
    channel: "normal", audioGen: false, audioLanguage: "english", negative: "", modeNote: "",
  }, init);
}

describe("priceKey: stable identity of the priced payload", () => {
  test("the DEFAULT skip list is exactly the fields that never price and are typed freely", () => {
    assert.deepEqual(PRICE_KEY_SKIP.slice().sort(), ["negative", "prompt", "seed"]);
  });

  test("drops ONLY the skipped fields -- every other field is part of the identity", () => {
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

  test("`seed` is in the default skip (image gen types it freely) and inert where no seed exists", () => {
    // Image gen's buildPayload carries a seed; the video/edit payloads do not, so listing it
    // costs those nothing. Proven directly against the key function.
    const withSeed = { version_id: "v", seed: "1234", width: 512 };
    assert.equal(priceKey(withSeed), priceKey({ ...withSeed, seed: "9999" }),
      "a seed change must not un-settle the verdict");
    assert.notEqual(priceKey(withSeed), priceKey({ ...withSeed, width: 768 }));
    const video = buildPayload(drawer({}), "");
    assert.ok(!("seed" in video), "the video payload has no seed -- the shared skip is inert there");
  });

  test("an EDIT payload skips its own free-text field (instruction), not `prompt`", () => {
    // buildEditPayload names the instruction `instruction`, so the shared default would leave it
    // IN the identity and every keystroke would un-settle the verdict and disable ✦ Edit.
    assert.ok(EDIT_PRICE_KEY_SKIP.indexOf("instruction") >= 0);
    PRICE_KEY_SKIP.forEach((k) => assert.ok(EDIT_PRICE_KEY_SKIP.indexOf(k) >= 0,
      "the edit skip list extends the shared default, it does not replace it: " + k));
    const s = { model: "edit-pro", source: "abc", refs: [], preset: "", resolution: "1K", quality: "high", aspect: "1:1" };
    const a = buildEditPayload({ ...s, instruction: "make it night" });
    const b = buildEditPayload({ ...s, instruction: "make it night, and add rain" });
    assert.equal(priceKey(a, EDIT_PRICE_KEY_SKIP), priceKey(b, EDIT_PRICE_KEY_SKIP),
      "an edit's price cannot move on its text -- a keystroke must not un-settle the verdict");
    assert.notEqual(priceKey(a, EDIT_PRICE_KEY_SKIP),
      priceKey(buildEditPayload({ ...s, instruction: "make it night", resolution: "2K" }), EDIT_PRICE_KEY_SKIP),
      "resolution DOES price -- it must stay in the key");
    // and with the default skip the same two keys diverge, which is exactly why the host passes its own
    assert.notEqual(priceKey(a), priceKey(b));
  });

  test("is stable across key order (it is an identity, not a serialization accident)", () => {
    const p = buildPayload(drawer({}), "");
    const shuffled = Object.keys(p).reverse().reduce((o, k) => (o[k] = p[k], o), {});
    assert.equal(priceKey(shuffled), priceKey(p));
  });

  test("tolerates junk without throwing (a null payload keys to nothing, never to something)", () => {
    assert.equal(priceKey(null), "");
    assert.equal(priceKey(undefined), "");
    assert.equal(canSubmit(settledFor(priceKey({ a: 1 })), null), false);
  });
});

describe("the verdict state machine", () => {
  test("the four constructors are the only shapes, and only one of them opens the gate", () => {
    const p = buildPayload(drawer({}), "");
    assert.deepEqual(initialVerdict(), { settled: false, pricedKey: null, pendingTimer: false });
    assert.deepEqual(scheduled(), { settled: false, pricedKey: null, pendingTimer: true });
    assert.deepEqual(fired(), { settled: false, pricedKey: null, pendingTimer: false });
    assert.deepEqual(settledFor("k"), { settled: true, pricedKey: "k", pendingTimer: false });
    assert.equal(canSubmit(initialVerdict(), p), false, "never priced -> fail closed");
    assert.equal(canSubmit(scheduled(), p), false, "a scheduled re-price disables Go outright");
    assert.equal(canSubmit(fired(), p), false, "fired but unsettled -> the answer is not back");
    assert.equal(canSubmit(settledFor(priceKey(p)), p), true);
  });
});

describe("canSubmit: the Go gate is payload identity, not timing", () => {
  test("MONEY TRIGGER 15s -> 5s -> 15s: a settled 5s verdict never carries a 15s submit", () => {
    const d = drawer({ duration: 15 });
    let v = settledFor(priceKey(buildPayload(d, "")));
    assert.equal(canSubmit(v, buildPayload(d, "")), true, "settled for THIS payload -> Go");
    // user picks 5s: the probe schedules, then fires, then settles for 5s
    d.duration = 5;
    assert.equal(canSubmit(v, buildPayload(d, "")), false, "the 15s verdict is not the 5s payload's");
    v = scheduled();
    assert.equal(canSubmit(v, buildPayload(d, "")), false);
    v = fired();
    assert.equal(canSubmit(v, buildPayload(d, "")), false);
    v = settledFor(priceKey(buildPayload(d, "")));
    assert.equal(canSubmit(v, buildPayload(d, "")), true, "settled FREE for 5s -> Go on the 5s payload");
    // the race: user flips back to 15s; the badge still says FREE (for 5s) and no timer has fired
    d.duration = 15;
    assert.equal(canSubmit(v, buildPayload(d, "")), false,
      "the badge's settled FREE is for the 5s payload -- a 15s submit against it is the stale-FREE spend");
    v = scheduled();
    assert.equal(canSubmit(v, buildPayload(d, "")), false, "a pending re-price disables Go outright");
  });

  test("quality change with NO re-price: the settled key no longer matches, Go is off", () => {
    const d = drawer({ quality: "professional" });
    const v = settledFor(priceKey(buildPayload(d, "")));
    d.quality = "basic";   // the old Quality onChange mutated exactly this and scheduled nothing
    assert.equal(canSubmit(v, buildPayload(d, "")), false,
      "i2vPro.mode rides the priced payload -- a professional quote must not carry a basic submit (or vice versa)");
    d.quality = "professional";
    assert.equal(canSubmit(v, buildPayload(d, "")), true, "restoring the priced value restores the match");
  });

  test("camera change with NO re-price: same story (i2vPro.cameraMovement is priced)", () => {
    const d = drawer({ camera: "unset" });
    const v = settledFor(priceKey(buildPayload(d, "")));
    d.camera = "zoom";
    assert.equal(canSubmit(v, buildPayload(d, "")), false);
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
    const v = settledFor(priceKey(buildPayload(d, "first draft")));
    assert.equal(canSubmit(v, buildPayload(d, "second draft, much longer")), true);
  });
});

describe("shouldShortCircuit: an unchanged settled key needs no new check", () => {
  test("a prompt-only change short-circuits -- no badge blank, no disabled button, no PixAI call", () => {
    const d = drawer({});
    const v = settledFor(priceKey(buildPayload(d, "first draft")));
    assert.equal(shouldShortCircuit(v, buildPayload(d, "a much longer second draft"), false), true);
  });

  test("a PRICED change never short-circuits", () => {
    const d = drawer({ duration: 5 });
    const v = settledFor(priceKey(buildPayload(d, "")));
    d.duration = 15;
    assert.equal(shouldShortCircuit(v, buildPayload(d, ""), false), false);
  });

  test("`force` bypasses it -- the post-submit re-price must not be swallowed", () => {
    // A submit DEBITS the tickets, so the settled verdict is stale even though the payload is
    // byte-identical; identity-by-payload cannot see a balance change (the exact #15 shape).
    const d = drawer({});
    const v = settledFor(priceKey(buildPayload(d, "")));
    assert.equal(shouldShortCircuit(v, buildPayload(d, ""), false), true, "unforced: nothing changed");
    assert.equal(shouldShortCircuit(v, buildPayload(d, ""), true), false, "forced: re-price anyway");
  });

  test("un-settled and pending states always fall through, so a genuine re-price is never suppressed", () => {
    const d = drawer({});
    const p = buildPayload(d, "");
    assert.equal(shouldShortCircuit(initialVerdict(), p, false), false);
    assert.equal(shouldShortCircuit(scheduled(), p, false), false);
    assert.equal(shouldShortCircuit(fired(), p, false), false);
    assert.equal(shouldShortCircuit({ settled: true, pricedKey: priceKey(p), pendingTimer: true }, p, false), false);
    assert.equal(shouldShortCircuit(null, p, false), false);
  });

  test("it honours a host's own skip list", () => {
    const s = { model: "edit-pro", source: "abc", refs: [], preset: "", resolution: "1K", quality: "high", aspect: "1:1" };
    const v = settledFor(priceKey(buildEditPayload({ ...s, instruction: "a" }), EDIT_PRICE_KEY_SKIP));
    const typed = buildEditPayload({ ...s, instruction: "a much longer instruction" });
    assert.equal(shouldShortCircuit(v, typed, false, EDIT_PRICE_KEY_SKIP), true);
    assert.equal(shouldShortCircuit(v, typed, false), false, "with the default skip it would re-price on every keystroke");
  });
});

describe("the idle verdict keeps the host's own refusal reachable", () => {
  test("an idle build settles for its payload, so the gate is OPEN and doGenerate does the refusing", () => {
    // "Nothing to price" is a VERDICT, not a gap: the badge clears to its hint and the verdict
    // settles on that same payload's key. If it left the verdict unsettled instead, the submit
    // control would be dead with no message -- the host's own "Pick a source image first" line
    // would never be reachable, which is the fail-silent-closed shape the review named.
    const d = drawer({ slots: [null] });          // no refs at all
    const p = buildPayload(d, "");
    const v = settledFor(priceKey(p));            // what the probe's idle branch writes
    assert.equal(canSubmit(v, p), true, "idle settles -> the click reaches the host's own error line");
  });
});

describe("timing constants", () => {
  test("one debounce and one abort ceiling for every cost line", () => {
    assert.equal(PRICE_DEBOUNCE_MS, 250, "all six hosts shipped 250 independently");
    assert.equal(PRICE_FETCH_TIMEOUT_MS, 25000,
      "Go is gated on the fetch settling, so an unbounded hang would disable it forever");
  });
});

describe("videoDrawerCore keeps re-exporting what moved", () => {
  test("the old import surface still resolves (existing call sites and tests must not break)", async () => {
    const core = await import("../../gallery/src/gen/videoDrawerCore.js");
    assert.equal(core.priceKey, priceKey);
    assert.equal(core.canSubmit, canSubmit);
    assert.equal(core.PRICE_FETCH_TIMEOUT_MS, PRICE_FETCH_TIMEOUT_MS);
    assert.deepEqual(core.PRICE_KEY_SKIP, PRICE_KEY_SKIP);
  });
});

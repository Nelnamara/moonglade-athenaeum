/* PHONES OPEN THE PHONE LAYOUT BY THEMSELVES (2026-09-06, owner call 5).

   Verbatim: "Yes, I want to be mindful of the tablet still being able to use desktop...
   I don't want a Tablet design pass anytime soon :|"

   So the gate is the app's ONE existing phone rule (gallery/src/hooks/useIsMobile.js), not
   a new threshold: a tablet's screen.width is above its 430px clause, so a tablet stays on
   the desktop build BY CONSTRUCTION rather than by a second number somebody has to keep in
   step. That is what the "tablet" tests below actually pin -- the rule the Loom defers to,
   and the fact that it defers rather than re-deciding.

   Both manual switches stay, and a flip of either wins forever after, in both directions.
   Only the AUTO half is new -- the switches' own wiring is tested in loom-mobile-view.test.js. */

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  LOOM_VIEW_KEY, LEGACY_MOBILE_UI_KEY, readStoredView, resolveLoomView,
} from "../src/loom-url.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rd = (p) => readFileSync(path.resolve(__dirname, "..", p), "utf8");
const loom = rd("master-storyboard.jsx");
const isMobileSrc = rd("../gallery/src/hooks/useIsMobile.js");

const store = (seed) => ({ getItem: (k) => (k in seed ? seed[k] : null) });

describe("resolveLoomView -- an explicit choice wins, otherwise follow the phone rule", () => {
  test("no answer yet: a phone opens the phone layout, everything else does not", () => {
    assert.equal(resolveLoomView(null, true), true);
    assert.equal(resolveLoomView(null, false), false);
  });

  test("a chosen 'mobile' holds even on a desktop", () => {
    assert.equal(resolveLoomView("mobile", false), true);
  });

  test("a chosen 'desktop' holds even on a phone -- never a one-way trap", () => {
    assert.equal(resolveLoomView("desktop", true), false);
  });
});

describe("readStoredView -- what counts as an answer", () => {
  test("the two real answers read back", () => {
    assert.equal(readStoredView(store({ [LOOM_VIEW_KEY]: "mobile" })), "mobile");
    assert.equal(readStoredView(store({ [LOOM_VIEW_KEY]: "desktop" })), "desktop");
  });

  test("nothing stored is 'never asked', not 'asked for desktop'", () => {
    assert.equal(readStoredView(store({})), null);
    assert.equal(readStoredView(store({ [LOOM_VIEW_KEY]: "nonsense" })), null);
    assert.equal(readStoredView(null), null);
  });

  test("the LEGACY key's '1' was a deliberate tick, so it is honoured as a choice", () => {
    assert.equal(readStoredView(store({ [LEGACY_MOBILE_UI_KEY]: "1" })), "mobile");
  });

  test("the legacy '0' is discarded -- the old hook wrote it on mount, nobody chose it", () => {
    // This is the whole reason the key changed: gated on the old value, the auto-open could
    // never fire on a phone that had ever opened the Loom.
    assert.equal(readStoredView(store({ [LEGACY_MOBILE_UI_KEY]: "0" })), null);
  });

  test("the new key outranks the legacy one", () => {
    assert.equal(readStoredView(store({
      [LOOM_VIEW_KEY]: "desktop", [LEGACY_MOBILE_UI_KEY]: "1",
    })), "desktop");
  });

  test("storage that throws is 'never asked', not a crash", () => {
    assert.equal(readStoredView({ getItem() { throw new Error("denied"); } }), null);
  });
});

describe("the phone rule the Loom defers to still excludes tablets", () => {
  test("the Loom keys on useIsMobile itself -- it does not re-decide what a phone is", () => {
    assert.match(loom, /import useIsMobile from "\.\.\/gallery\/src\/hooks\/useIsMobile\.js";/);
    assert.match(loom, /const \[mobileUI, setMobileUI\] = useLoomView\(useIsMobile\(\)\);/);
    assert.equal((loom.match(/useIsMobile\(/g) || []).length, 1,
      "exactly one call site -- a second would be a second opinion about what a phone is");
    assert.doesNotMatch(loom, /max-width:\s*\d+px\)"/,
      "no hand-rolled viewport query in the Loom; the rule lives in one file");
  });

  test("that rule is still the 430px one, with its coarse-pointer fallback", () => {
    assert.match(isMobileSrc, /const MOBILE_QUERY = "\(max-width: 430px\)";/);
    assert.match(isMobileSrc, /coarse && portrait && screenW <= 430/,
      "the fallback's screen.width clause is what keeps a real tablet on the desktop build");
  });

  test("a tablet fails it by construction: coarse and portrait are not enough", () => {
    // The rule as code, driven the only way a pure test can drive it -- the two clauses
    // that decide, in the same order the hook evaluates them. An iPad in portrait is
    // coarse-pointer and portrait, and its screen.width (768+) is what refuses it.
    const rule = (layoutW, coarse, portrait, screenW) =>
      layoutW <= 430 || (coarse && portrait && screenW <= 430);
    assert.equal(rule(390, true, true, 390), true, "iPhone portrait is a phone");
    assert.equal(rule(1024, true, true, 390), true, "iOS Chrome's desktop-wide viewport, still a phone");
    assert.equal(rule(768, true, true, 768), false, "iPad portrait stays on desktop");
    assert.equal(rule(1024, true, false, 1024), false, "iPad landscape stays on desktop");
    assert.equal(rule(1440, false, false, 1440), false, "a laptop stays on desktop");
  });
});

describe("both manual switches survive the auto-open", () => {
  test("the top bar's 'Mobile view' checkbox still writes a real choice", () => {
    assert.match(loom, /onChange=\{\(e\) => setMobileUI\(e\.target\.checked\)\}/);
  });

  test("LoomMobile's reciprocal 'Desktop' chip still writes one too", () => {
    assert.match(loom, /onClick=\{\(\) => setMobileUI\(false\)\}/);
  });

  test("the key is written ONLY by a flip -- never on mount, or absent stops meaning 'not asked'", () => {
    const idx = loom.indexOf("function useLoomView(isPhone)");
    assert.ok(idx > 0, "expected useLoomView");
    const hook = loom.slice(idx, idx + 900);
    assert.match(hook, /const setMobileUI = useCallback\(\(v\) => \{/);
    assert.match(hook, /window\.localStorage\.setItem\(LOOM_VIEW_KEY, next \? "mobile" : "desktop"\)/);
    assert.doesNotMatch(hook, /useEffect\(/,
      "an effect writing the value back is exactly the bug the new key exists to undo");
  });

  test("the rotate note's own words are left alone -- that half is the Design Handoff's", () => {
    const mobileApp = rd("../gallery/src/components/AppMobile.jsx");
    assert.match(mobileApp, /<b>Rotate to landscape<\/b>/);
  });
});

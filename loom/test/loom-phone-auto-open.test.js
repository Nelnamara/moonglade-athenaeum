/* PHONES OPEN THE PHONE LAYOUT BY THEMSELVES (2026-09-06, owner call 5).

   Verbatim: "Yes, I want to be mindful of the tablet still being able to use desktop...
   I don't want a Tablet design pass anytime soon :|"

   So the gate is the app's ONE existing phone rule (gallery/src/hooks/useIsMobile.js), not
   a new threshold: a tablet's screen.width is above its 520px clause, so a tablet stays on
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

  test("a legacy '0' is an answer too -- the browser had it, so nobody is switched under them", () => {
    /* The migration's original premise was "the old hook wrote 0 on mount, so nobody chose
       it". True for a browser that never touched the switch -- but that hook wrote on EVERY
       change of the value, so a real, deliberate uncheck of the old "Mobile view" box wrote
       exactly the same 0. The two are indistinguishable in the stored data, so discarding
       it silently reversed the choice of everyone who had turned the old switch back to
       desktop: the one-way trap this feature's own comments say it avoids.

       Presence of the legacy key, at ANY value, is therefore treated as "this browser has
       been here and has an answer". Only a browser with NEITHER key gets the auto-open. */
    assert.equal(readStoredView(store({ [LEGACY_MOBILE_UI_KEY]: "0" })), "desktop");
    assert.equal(readStoredView(store({ [LEGACY_MOBILE_UI_KEY]: "" })), "desktop");
    assert.equal(readStoredView(store({ [LEGACY_MOBILE_UI_KEY]: "junk" })), "desktop");
    // and that answer really holds the phone on the desktop build
    assert.equal(resolveLoomView(readStoredView(store({ [LEGACY_MOBILE_UI_KEY]: "0" })), true),
      false);
    // a browser with neither key is the only one the auto-open speaks for
    assert.equal(resolveLoomView(readStoredView(store({})), true), true);
  });

  test("a new flip still outranks the legacy answer, in both directions", () => {
    assert.equal(readStoredView(store({
      [LOOM_VIEW_KEY]: "mobile", [LEGACY_MOBILE_UI_KEY]: "0",
    })), "mobile");
    assert.equal(readStoredView(store({
      [LOOM_VIEW_KEY]: "desktop", [LEGACY_MOBILE_UI_KEY]: "1",
    })), "desktop");
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

  test("that rule is still the one width line (520px since 2026-09-07), with its coarse-pointer fallback", () => {
    assert.match(isMobileSrc, /const MOBILE_QUERY = "\(max-width: 520px\)";/);   // 430 -> 520 on 2026-09-07: the Pro Max class is 440 wide
    assert.match(isMobileSrc, /coarse && portrait && screenW <= 520/,
      "the fallback's screen.width clause is what keeps a real tablet on the desktop build");
  });

  test("a tablet fails it by construction: coarse and portrait are not enough", () => {
    // The rule as code, driven the only way a pure test can drive it -- the two clauses
    // that decide, in the same order the hook evaluates them. An iPad in portrait is
    // coarse-pointer and portrait, and its screen.width (768+) is what refuses it.
    const rule = (layoutW, coarse, portrait, screenW) =>
      layoutW <= 520 || (coarse && portrait && screenW <= 520);
    assert.equal(rule(390, true, true, 390), true, "iPhone portrait is a phone");
    assert.equal(rule(440, true, true, 440), true, "an iPhone Pro Max (440 wide since the 16) is a phone -- the 2026-09-07 case");
    assert.equal(rule(489, true, true, 440), true, "the same phone with Safari page zoom at 90% is still a phone");
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

  test("the auto-open is decided ONCE, so a rotation cannot swap the whole shell mid-session", () => {
    /* useIsMobile is deliberately live: it subscribes to matchMedia, resize and
       orientationchange so the presentation flips with the device. Re-deriving the Loom's
       view from it on every render made ordinary ROTATION a full unmount/remount between
       LoomMobile and LoomV2 -- a phone user watching a clip in Review & trim turns the
       phone to see it wider and the review closes, because that state is LoomMobile's own
       and dies with the subtree.

       The decision is a default, not a live reading: taken once, on mount, and changed
       after that only by a switch the owner actually flips. */
    const idx = loom.indexOf("function useLoomView(isPhone)");
    const hook = loom.slice(idx, loom.indexOf("\n}\n", idx));
    // the rule is consulted exactly once, and it is inside the state initializer
    assert.equal((hook.match(/resolveLoomView\(/g) || []).length, 1,
      "a second call is a second, live decision -- which is the remount-on-rotate bug");
    const init = hook.slice(hook.indexOf("useState("), hook.indexOf("const setMobileUI"));
    assert.match(init, /resolveLoomView\(/,
      "the resolved view must be SEEDED once, not recomputed every render");
    assert.match(hook, /return \[mobileUI, setMobileUI\];/,
      "the hook returns the state it holds, not a value re-derived from a live isPhone");
  });

  test("the same phone rule still decides that one-time default", () => {
    // Rotation must not RE-decide, but the first answer is still the app's one phone rule.
    assert.equal(resolveLoomView(null, true), true);
    assert.equal(resolveLoomView(null, false), false);
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

  test("the phone's Loom sheet describes the layout it actually opens", () => {
    /* It used to say "Rotate to landscape -- the Loom is built for the wide surface, and
       portrait stays cramped", directly above the button that now opens a portrait-built
       board-and-reel view. The sheet was contradicting the app. Landscape advice belongs
       to the desktop board, which is a choice away, so that is where it sits now. */
    const mobileApp = rd("../gallery/src/components/AppMobile.jsx");
    const sheet = mobileApp.slice(mobileApp.indexOf('title="THE LOOM"'));
    const note = sheet.slice(0, sheet.indexOf("</MobileSheet>"));
    assert.doesNotMatch(note, /<b>Rotate to landscape<\/b>/,
      "the unconditional rotate instruction is no longer true on a phone");
    assert.match(note, /board and reel/);
    assert.match(note, /Desktop/, "and the wide board is still findable, as the override");
  });
});

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  BUBBLE_MS, SIGNED_IN_KEY, STRIP_TEXT, bubbleSide, bubbleText, isInAppBrowser, isIosSafari, isStandalone,
  markSignedIn, nudgePlatform, readAndClearSignedIn, shouldNudge,
} from "../../gallery/src/lib/installNudge.js";
import { NUDGE_OFF_KEY, readNudgeOff, writeNudgeOff } from "../../gallery/src/lib/phonePrefs.js";

/* Session U, the Home Screen nudge (Phone Paging and Nudge Handoff.dc.html, U6c + U7b): once, after a
   sign-in, on a phone browser that can add the app to its Home Screen and has not; iOS Safari gets a
   bubble at its Share button, Android the browser's own install prompt, anything else nothing. And the
   QR the phone arrives by stays a bare address. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const code = (rel) => readFileSync(path.join(SRC, rel), "utf8").split("\r\n").join("\n")
  .replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");

const UA = {
  iosSafari: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
  iosChrome: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/126.0.6478.54 Mobile/15E148 Safari/604.1",
  iosFirefox: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/127.0 Mobile/15E148 Safari/605.1.15",
  iosInstagram: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 330.0.0.0",
  iosFacebook: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 [FBAN/FBIOS;FBAV/470.0]",
  androidChrome: "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
  androidWebView: "Mozilla/5.0 (Linux; Android 14; Pixel 8; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/126.0.0.0 Mobile Safari/537.36",
};

function recorder(seed) {
  const data = new Map(Object.entries(seed || {}));
  const log = [];
  return {
    log, data,
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => { log.push(["set", k, v]); data.set(k, String(v)); },
    removeItem: (k) => { log.push(["remove", k]); data.delete(k); },
  };
}

describe("U6/U7 who sees the nudge", () => {
  test("iOS Safari, and only Safari: not Chrome or Firefox on iOS, not an in-app browser", () => {
    assert.equal(isIosSafari(UA.iosSafari), true);
    for (const k of ["iosChrome", "iosFirefox", "iosInstagram", "iosFacebook", "androidChrome"]) {
      assert.equal(isIosSafari(UA[k]), false, k);
    }
    assert.equal(isInAppBrowser(UA.iosInstagram), true);
    assert.equal(isInAppBrowser(UA.iosFacebook), true);
    assert.equal(isInAppBrowser(UA.androidWebView), true);
    assert.equal(isInAppBrowser(UA.iosSafari), false);
  });

  test("installed already (display-mode standalone, or iOS's navigator.standalone) is never nudged", () => {
    assert.equal(isStandalone({ displayStandalone: true, navigatorStandalone: undefined }), true);
    assert.equal(isStandalone({ displayStandalone: false, navigatorStandalone: true }), true);
    assert.equal(isStandalone({ displayStandalone: false, navigatorStandalone: false }), false);
  });

  test("iOS Safari gets the bubble; a browser holding an install prompt gets the prompt; elsewhere nothing", () => {
    assert.equal(nudgePlatform({ ua: UA.iosSafari, standalone: false, canPrompt: false }), "ios");
    assert.equal(nudgePlatform({ ua: UA.androidChrome, standalone: false, canPrompt: true }), "android");
    assert.equal(nudgePlatform({ ua: UA.androidChrome, standalone: false, canPrompt: false }), "", "no prompt offered: nothing");
    assert.equal(nudgePlatform({ ua: UA.iosChrome, standalone: false, canPrompt: false }), "");
    assert.equal(nudgePlatform({ ua: UA.iosSafari, standalone: true, canPrompt: false }), "", "already on the Home Screen");
    assert.equal(nudgePlatform({ ua: UA.androidWebView, standalone: false, canPrompt: true }), "", "an in-app browser, never");
  });

  test("once, right after a sign-in, and never after ✕ on this device", () => {
    assert.equal(shouldNudge({ signedIn: true, dismissed: false, platform: "ios" }), true);
    assert.equal(shouldNudge({ signedIn: false, dismissed: false, platform: "ios" }), false, "no sign-in, no nudge");
    assert.equal(shouldNudge({ signedIn: true, dismissed: true, platform: "ios" }), false);
    assert.equal(shouldNudge({ signedIn: true, dismissed: false, platform: "" }), false);
  });

  test("the sign-in mark is read once and taken away, so a reload does not nudge again", () => {
    const s = recorder();
    assert.equal(markSignedIn(s), true);
    assert.equal(s.data.get(SIGNED_IN_KEY), "1");
    assert.equal(readAndClearSignedIn(s), true);
    assert.equal(s.data.has(SIGNED_IN_KEY), false);
    assert.equal(readAndClearSignedIn(s), false);
    const throwing = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); }, removeItem() { throw new Error("blocked"); } };
    assert.equal(markSignedIn(throwing), false);
    assert.equal(readAndClearSignedIn(throwing), false);
  });

  test("✕ is kept per device, written only by the ✕, and a fresh phone reads 'not dismissed' without writing", () => {
    const s = recorder();
    assert.equal(readNudgeOff(s), false);
    assert.deepEqual(s.log, []);
    assert.equal(writeNudgeOff(s), true);
    assert.equal(s.data.get(NUDGE_OFF_KEY), "1");
    assert.equal(readNudgeOff(s), true);
  });
});

describe("U6/U7 what it says", () => {
  test("the strip and the bubble, in the page's words; it explains adding to the Home Screen only", () => {
    assert.equal(STRIP_TEXT, "Add to Home Screen for full screen ›");
    assert.equal(bubbleText("bottom"), 'Tap ⬆ below, then "Add to Home Screen".');
    assert.equal(bubbleText("top"), 'Tap ⬆ above, then "Add to Home Screen".');
    for (const t of [STRIP_TEXT, bubbleText("bottom"), bubbleText("top")]) {
      assert.doesNotMatch(t, /offline|notif|signed in|stay|log ?in|password/i, t);
    }
  });

  test("the bubble points down at Safari's toolbar, or up under a top address bar (sideways); 8 s", () => {
    assert.equal(bubbleSide(false), "bottom");
    assert.equal(bubbleSide(true), "top");
    assert.equal(BUBBLE_MS, 8000);
  });
});

describe("U6/U7 the wiring", () => {
  test("a successful sign-in marks the visit before the page moves on", () => {
    const login = code("hooks/useLogin.js");
    assert.match(login, /setPhase\("welcome"\);\s*markSignedIn\(\);\s*window\.location\.href = d\.next \|\| "\/";/);
  });

  test("the strip sits under the gallery's pill row and pushes the grid down; ✕ and a tap are its only writes", () => {
    const g = code("components/GalleryMobile.jsx");
    const bar2 = g.indexOf('className={"glm-bar2"');
    const strip = g.indexOf("<NudgeStrip");
    const grid = g.indexOf("<ContinuousGridMobile");
    assert.ok(bar2 > 0 && strip > bar2 && strip < grid, "after the pill row, before the grid");
    const hook = code("hooks/useInstallNudge.js");
    assert.match(hook, /const dismiss = useCallback\(\(\) => \{ writeNudgeOff\(\);/);
    assert.match(hook, /e\.preventDefault\(\);\s*deferred = e;/);
    assert.match(hook, /if \(readNudgeOff\(\)\) return;/, "waved off: the browser keeps its own install offer");
    assert.match(hook, /setTimeout\(\(\) => setBubble\(""\), BUBBLE_MS\)/);
    assert.match(hook, /document\.addEventListener\("pointerdown", close, true\)/);
  });

  test("the first-run guide stands aside while the bubble is up", () => {
    const app = code("components/AppMobile.jsx");
    assert.match(app, /paused=\{!!sheet \|\| claimModal\.open \|\| !!nudge\.bubble\}/);
  });

  test("the QR stays a bare address: what it encodes is the reachable URL, nothing added", () => {
    const card = code("components/BonjourCard.jsx");
    assert.match(card, /const url = \(st\.reachable_urls && st\.reachable_urls\[0\]\) \|\| "";/);
    assert.match(card, /qrDataUrl\(url\)/);
    // no session, token, next or credential: nothing but the address goes into the QR
    const credential = /csrf|token|\bsession\b|session_?id|[?&]next=|password|document\.cookie/i;
    assert.doesNotMatch(card, credential);
    for (const rel of ["lib/installNudge.js", "hooks/useInstallNudge.js", "components/InstallNudge.jsx"]) {
      assert.doesNotMatch(code(rel), credential, rel);
    }
  });
});

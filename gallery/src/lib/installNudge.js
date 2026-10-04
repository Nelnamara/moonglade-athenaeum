/* The Home Screen nudge (Session U, Phone Paging and Nudge Handoff.dc.html U6c + U7b): the pure rules.
   No DOM and no network; storage is a parameter (the real one by default) so loom/test/phone-nudge.test.js
   holds every rule as the page states it. hooks/useInstallNudge.js reads the browser and draws nothing;
   components/InstallNudge.jsx draws.

   WHEN. Once, right after a successful sign-in, on a phone browser that can add the app to its Home
   Screen and has not: iOS Safari (Share -> Add to Home Screen), or a browser that has offered its own
   install prompt (Android Chrome). Never in an in-app browser, never when the app is already open from
   the Home Screen, never after ✕ on this device (lib/phonePrefs.js). Anywhere else: nothing.

   WHAT. A 36 px strip under the gallery's pill row -- "Add to Home Screen for full screen ›" and ✕. On
   iOS its tap shows a bubble at Safari's Share button for 8 s (or until any tap); on Android it fires the
   browser's own install prompt. It explains adding to the Home Screen and nothing else: no promise of
   offline use, notifications or staying signed in. The QR a phone arrives by is not this file's: it
   stays a bare address (BonjourCard.jsx), and nothing here builds a link of any kind. */

export const STRIP_TEXT = "Add to Home Screen for full screen ›";
export const BUBBLE_MS = 8000;
export const SIGNED_IN_KEY = "mg_signed_in";      // sessionStorage, set by a successful sign-in

const IN_APP = /FBAN|FBAV|FB_IAB|FBIOS|Instagram|Line\/|MicroMessenger|Twitter|Snapchat|Pinterest|LinkedInApp|GSA\/|; wv\)/i;
const IOS_DEVICE = /iPhone|iPod|iPad/;
const IOS_NOT_SAFARI = /CriOS|FxiOS|EdgiOS|OPiOS|OPT\/|DuckDuckGo|YaBrowser|Brave|Mercury/i;

export function isInAppBrowser(ua) {
  return IN_APP.test(String(ua || ""));
}

/* iOS Safari itself: an iOS device, Safari's Version/ and Safari/ tokens, and none of the other iOS
   browsers' or an app's own marks. */
export function isIosSafari(ua) {
  const s = String(ua || "");
  return IOS_DEVICE.test(s) && /Version\//.test(s) && /Safari\//.test(s) && !IOS_NOT_SAFARI.test(s) && !isInAppBrowser(s);
}

/* Already on the Home Screen: the display-mode media query, or iOS's own navigator.standalone. */
export function isStandalone({ displayStandalone, navigatorStandalone }) {
  return !!displayStandalone || navigatorStandalone === true;
}

/* "ios" (the Share bubble), "android" (the browser's own prompt, held back for the strip), or "". */
export function nudgePlatform({ ua, standalone, canPrompt }) {
  if (standalone || isInAppBrowser(ua)) return "";
  if (isIosSafari(ua)) return "ios";
  return canPrompt ? "android" : "";
}

export function shouldNudge({ signedIn, dismissed, platform }) {
  return !!signedIn && !dismissed && !!platform;
}

/* Safari's toolbar is at the bottom on an upright iPhone; held sideways its address bar and Share
   button are at the top. Whether the owner moved the address bar to the top is a Safari setting a page
   cannot read, so the bubble follows the way the phone is held. */
export function bubbleSide(landscape) {
  return landscape ? "top" : "bottom";
}

export function bubbleText(side) {
  return "Tap ⬆ " + (side === "top" ? "above" : "below") + ', then "Add to Home Screen".';
}

function tabStore(storage) {
  if (storage) return storage;
  try { return typeof sessionStorage !== "undefined" ? sessionStorage : null; } catch { return null; }
}

/* The sign-in's mark on this tab: set by a successful sign-in, read once by the gallery and taken away,
   so the nudge shows on the visit the sign-in lands on and not on a reload. Storage that throws is
   "no mark" -- the phone then simply does not nudge. */
export function markSignedIn(storage) {
  try {
    const s = tabStore(storage);
    if (!s) return false;
    s.setItem(SIGNED_IN_KEY, "1");
    return true;
  } catch { return false; }
}

export function readAndClearSignedIn(storage) {
  try {
    const s = tabStore(storage);
    if (!s || s.getItem(SIGNED_IN_KEY) !== "1") return false;
    s.removeItem(SIGNED_IN_KEY);
    return true;
  } catch { return false; }
}

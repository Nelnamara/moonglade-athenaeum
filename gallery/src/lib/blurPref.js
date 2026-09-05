/* blurPref -- "Blur behind popups", the one per-device display preference.

   WHAT IT CONTROLS. Every popup in the app lands on a dark scrim, and that scrim carries a
   `backdrop-filter` over whatever the popup covers -- usually a live 100-card grid. The
   2026-09-04 perf pass moved WHEN that blur turns on (after the fade, never during it), so
   the OPEN got cheap; the blur itself still costs for as long as the popup is up. On a weak
   machine that is the largest bill an overlay runs up. This preference turns it off. The
   dark scrim stays exactly as it is -- same colour, same fade, same timing. Off, the
   gallery behind the popup is simply sharp.

   WHY BROWSER STORAGE AND NOT config.json (owner ruling, DECISIONS.md 2026-09-04, "the
   popup blur gets a Control Panel toggle"): it is a property of the DEVICE, not of the
   account. The same owner wants it off on a phone and on at the home desktop, and a
   server-side setting cannot be both. So it lives in localStorage, per browser, and the
   Control Panel writes it -- there is no API call and no round trip.

   HOW IT REACHES THE CSS. One class on <html>, `mg-noblur`, which each of the seven scrim
   rules answers with a `backdrop-filter: none !important` of its own (canonical explanation:
   gallery/src/styles/overlays.css, "THE BLUR SWITCH"). The class is the whole contract --
   no inline styles, no per-element bookkeeping, and flipping it is one classList call that
   applies to a popup already on screen.

   IMPORTANT, and asserted in loom/test/blur-pref.test.js: the stored value means BLUR OFF,
   not blur on. Blur is the default and the historical behaviour, so an install that has
   never touched this toggle -- and a browser that refuses storage entirely -- must look
   exactly like it always has. Only an explicit "1" turns the blur off. */

export const BLUR_OFF_KEY = "mg_noblur";
export const NOBLUR_CLASS = "mg-noblur";

/** Is the blur currently switched OFF for this device? Storage can throw outright in
    private mode / with site data blocked, and the honest answer there is "no preference
    stored", which means the default: blur ON. Same try/catch discipline as
    notify/jobsStore.js and NavSpine.jsx. */
export function isBlurOff() {
  try { return localStorage.getItem(BLUR_OFF_KEY) === "1"; } catch { return false; }
}

/** Write the preference. Storing "" rather than removing the key matches App.jsx's own
    boolean prefs (gallery_privacy_blur, mg_banner_slim) -- both read `=== "1"`, so an
    empty string and a missing key are the same "blur on" to every reader. */
export function setBlurOff(off) {
  try { localStorage.setItem(BLUR_OFF_KEY, off ? "1" : ""); } catch { /* private mode */ }
}

/** Put the class on (or take it off) a document root. Split from the storage half so the
    two can be tested apart, and so the boot path can apply a value it already has. */
export function applyBlurClass(root, off) {
  if (!root || !root.classList) return;
  if (off) root.classList.add(NOBLUR_CLASS);
  else root.classList.remove(NOBLUR_CLASS);
}

/** Read storage and apply, in one call. This is what main.jsx runs at boot and what the
    Control Panel toggle runs on every flip. Returns the value it applied. */
export function syncBlurClass(root) {
  const off = isBlurOff();
  applyBlurClass(root || (typeof document !== "undefined" ? document.documentElement : null), off);
  return off;
}

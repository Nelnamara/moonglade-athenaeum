/* INSTANT TIPS: the touch half of the shared `[data-tip]` tooltip (rule in styles.css,
   "INSTANT TIPS"). A native `title=` shows after a delay on a mouse hover and never on a
   phone or tablet, so the app's own words use `data-tip=` instead: a pointer gets the tip at
   once from CSS (:hover / :focus-visible), and a LONG PRESS (about 450 ms, finger still)
   gets it here by adding `is-tip-open` for about 2.5 s, or until the next touch anywhere.
   A normal tap is untouched. When a long press showed a tip, the click that would follow the
   lift is swallowed so the press does not also activate the button or open the link.
   One delegated set of listeners on the document; installTips() is idempotent. */

export const TIP_PRESS_MS = 450;
export const TIP_SHOW_MS = 2500;
const MOVE_SLOP = 10;
const OPEN = "is-tip-open";

export function installTips(doc) {
  doc = doc || (typeof document !== "undefined" ? document : null);
  if (!doc || doc.__mgTipsInstalled) return;
  doc.__mgTipsInstalled = true;

  let pressTimer = null, hideTimer = null, openEl = null, start = null, pressEl = null;
  let swallowUntil = 0;

  const closeTip = () => {
    if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
    if (openEl) { openEl.classList.remove(OPEN); openEl = null; }
  };
  const cancelPress = () => {
    if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; }
    pressEl = null;
  };
  const tipTarget = (t) => (t && t.closest ? t.closest("[data-tip]") : null);

  doc.addEventListener("touchstart", (e) => {
    closeTip();
    cancelPress();
    if (!e.touches || e.touches.length !== 1) return;
    const el = tipTarget(e.target);
    if (!el) return;
    const t = e.touches[0];
    start = { x: t.clientX, y: t.clientY };
    pressEl = el;
    pressTimer = setTimeout(() => {
      pressTimer = null;
      if (!pressEl) return;
      openEl = pressEl;
      openEl.classList.add(OPEN);
      swallowUntil = Date.now() + 5000;       // the lift's click, however late it lands
      hideTimer = setTimeout(closeTip, TIP_SHOW_MS);
    }, TIP_PRESS_MS);
  }, { passive: true, capture: true });

  doc.addEventListener("touchmove", (e) => {
    if (!pressTimer || !start || !e.touches || !e.touches[0]) return;
    const t = e.touches[0];
    if (Math.abs(t.clientX - start.x) > MOVE_SLOP || Math.abs(t.clientY - start.y) > MOVE_SLOP) cancelPress();
  }, { passive: true, capture: true });

  doc.addEventListener("touchend", () => { cancelPress(); }, { passive: true, capture: true });
  doc.addEventListener("touchcancel", () => { cancelPress(); closeTip(); }, { passive: true, capture: true });

  /* the click that follows a tip-showing long press must not also activate */
  doc.addEventListener("click", (e) => {
    if (swallowUntil && Date.now() < swallowUntil) {
      swallowUntil = 0;
      e.preventDefault();
      e.stopPropagation();
    }
  }, true);

  /* a long press on a link raises the browser's own menu; hold it back while a tip is
     what the press was for */
  doc.addEventListener("contextmenu", (e) => {
    if ((openEl || pressTimer || pressEl) && tipTarget(e.target)) e.preventDefault();
  }, true);
}

/* The code's TOUCH FORM (owner, 2026-09-26: a phone has no arrow keys, so the starfall could not
   be cast from one; "Yes" to a touch version). Eight swipes -- up, up, down, down, left, right,
   left, right -- then two taps for B and A, anywhere on the page.

   Read passively from touch events only: it never prevents a scroll, a swipe or a click, and a
   mouse or a pen never feeds it. Touch events rather than pointer events on purpose: a vertical
   swipe on a scrolling page makes the browser take the gesture, which CANCELS the pointer
   stream, while touchend still reports where the finger lifted.

   A tap on a control (a link, a button, a field) is not a B/A tap -- it breaks the sequence, so
   using the page never completes the code by accident -- and a pause longer than GAP_MS
   between two gestures starts it over. The classifier and the matcher are pure, for the tests. */

export const TOUCH_SEQ = ["U", "U", "D", "D", "L", "R", "L", "R", "T", "T"];

const SWIPE_MIN = 40;      // px the finger must travel for a swipe
const SWIPE_MS = 800;      // ...within this long
const TAP_MAX = 12;        // px a tap may drift
const TAP_MS = 350;        // ...within this long
export const GAP_MS = 2500;

const CONTROL = 'a,button,input,textarea,select,label,summary,[role="button"],[contenteditable="true"]';

/* One gesture -> "U" | "D" | "L" | "R" (a swipe, by its dominant axis; screen y grows downward,
   so a finger moving up is "U"), "T" (a tap off any control), "X" (a tap ON a control, which
   breaks the sequence), or null (neither: a slow drag, a long press -- ignored). */
export function classify(dx, dy, ms, onControl) {
  const dist = Math.hypot(dx, dy);
  if (dist <= TAP_MAX && ms <= TAP_MS) return onControl ? "X" : "T";
  if (dist >= SWIPE_MIN && ms <= SWIPE_MS) {
    if (Math.abs(dx) > Math.abs(dy)) return dx > 0 ? "R" : "L";
    return dy < 0 ? "U" : "D";
  }
  return null;
}

/* The sequence, read as the LAST len(seq) gestures: whatever came before -- a scroll swipe up
   just before the code, say -- cannot stop it. (A position counter, the key handler's way,
   loses the code after "up, up, up": it restarts at the third up and never sees the downs.)
   Returns true on the gesture that completes it, and starts clean after. */
export function createMatcher(seq = TOUCH_SEQ, gapMs = GAP_MS) {
  let buf = [];
  let last = -Infinity;
  return (g, now) => {
    if (g == null) return false;
    if (now - last > gapMs) buf = [];
    last = now;
    buf.push(g);
    if (buf.length > seq.length) buf.shift();
    if (buf.length !== seq.length || buf.some((x, i) => x !== seq[i])) return false;
    buf = [];
    return true;
  };
}

/* Listen on window; returns the teardown. */
export function installTouchCode(onMatch) {
  if (typeof window === "undefined") return () => {};
  const match = createMatcher();
  let start = null;
  const onStart = (e) => {
    if (!e.touches || e.touches.length !== 1) { start = null; return; }
    const t = e.touches[0];
    start = { x: t.clientX, y: t.clientY, at: e.timeStamp, target: e.target };
  };
  const onEnd = (e) => {
    const s = start;
    start = null;
    if (!s || !e.changedTouches || !e.changedTouches.length) return;
    const t = e.changedTouches[0];
    const onControl = !!(s.target && s.target.closest && s.target.closest(CONTROL));
    const g = classify(t.clientX - s.x, t.clientY - s.y, e.timeStamp - s.at, onControl);
    if (match(g, e.timeStamp)) onMatch();
  };
  const onCancel = () => { start = null; };
  const opts = { passive: true, capture: true };
  window.addEventListener("touchstart", onStart, opts);
  window.addEventListener("touchend", onEnd, opts);
  window.addEventListener("touchcancel", onCancel, opts);
  return () => {
    window.removeEventListener("touchstart", onStart, opts);
    window.removeEventListener("touchend", onEnd, opts);
    window.removeEventListener("touchcancel", onCancel, opts);
  };
}

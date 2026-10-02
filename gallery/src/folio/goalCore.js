/* THE GOAL CHIPS' PURE LOGIC (Session O, O4 the pinned goal, O5 the Vigil). Nothing here touches
   React, the DOM or the network, so loom/test/folio-goal-core.test.js holds every rule.

   FEATS LEAK NOTHING (Session G) holds here too: a pin can only ever resolve to an honor that
   completionistCore.progressOf answers for, and that is null for a feat of any kind, for an
   honor already earned and for a metric nobody measures. So an id a hand-edited account
   document names but that is a feat, or unknown, or done, draws no chip and no error. */

import { progressOf, jumpOf, toGoText } from "./completionistCore.js";

/* The account's own store (wave 1, /api/account/prefs): keys are lowercase dotted names. The
   pin is ONE honor id; the Vigil switch is a boolean. Both are written only by a click. */
export const PIN_KEY = "folio.pin";
export const VIGIL_HEADER_KEY = "folio.vigilheader";

const ID_MAX = 96;

/* The stored pin -> an id, or "" (none). Anything that is not a plain non-empty string of a
   sane length is no pin. */
export function pinnedId(prefsDoc) {
  const v = prefsDoc && prefsDoc[PIN_KEY];
  return typeof v === "string" && v.length > 0 && v.length <= ID_MAX ? v : "";
}

/* Is the Vigil switch on: only a real `true`. */
export function vigilInHeader(prefsDoc) {
  return !!prefsDoc && prefsDoc[VIGIL_HEADER_KEY] === true;
}

/* May this honor be pinned? Exactly when it has a count (progressOf), which is never a feat and
   never an unmeasured metric. The pin button is drawn only for these. */
export function canPin(a) {
  return progressOf(a) !== null;
}

/* What a click on an honor's pin button does to the stored pin: pinning the pinned honor lets
   go of it, pinning any other REPLACES it (one pin at a time). Returns the id to store, or ""
   to clear. An honor that cannot be pinned changes nothing (null: do not write). */
export function togglePin(currentId, a) {
  if (!a || !canPin(a)) return null;
  return a.id === currentId ? "" : a.id;
}

/* The chip's view of the pinned honor, or null (no chip): the moon's true fraction, the name,
   "N to go", and where the jump goes. Null when the id is empty, is not in the payload, or has
   no count (a feat, an unmeasured metric, or an honor already earned). `achievements` is the
   /api/achievements array, so an honor the account has since earned is null and the chip is
   simply gone. */
export function pinView(achievements, id) {
  if (!id || !Array.isArray(achievements)) return null;
  const a = achievements.find((x) => x && x.id === id);
  if (!a) return null;
  const p = progressOf(a);
  if (!p) return null;
  const jump = jumpOf(a);
  return {
    id: a.id, name: a.name || "", fraction: p.fraction, left: p.left,
    toGo: toGoText(p), text: (a.name || "") + " · " + toGoText(p),
    jump: jump ? jump.to : "",
  };
}

/* Should the pin be let go: the honor the account pinned is one of those the marking read has
   just reported as newly earned, so the earn toast plays and the chip goes with it. Only that
   event clears a pin: an honor found already earned on open just draws no chip (pinView), and
   nothing is written. */
export function pinEarned(id, newly) {
  return !!id && Array.isArray(newly) && newly.indexOf(id) >= 0;
}

/* ---- O5: the Vigil ------------------------------------------------------------------- */

const whole = (n) => typeof n === "number" && Number.isFinite(n) && n >= 1 && Math.floor(n) === n;

/* The payload's `vigil` -> the chip's view, or null when the server sent nothing usable (an
   older server, a bad answer): {day, best, text: "Vigil · day 6", bestText: "best 6"}. The count
   only ever says where the run is. A miss shows as a smaller number and nothing else: no
   message, no warning, no toast. `best` is never shown below the day. */
export function vigilView(vigil) {
  if (!vigil || typeof vigil !== "object") return null;
  const day = vigil.day, best = vigil.best;
  if (!whole(day)) return null;
  const b = whole(best) ? Math.max(best, day) : day;
  return { day, best: b, text: "Vigil · day " + day, bestText: "best " + b };
}

/* ---- the phone's swipe --------------------------------------------------------------- */

export const SWIPE = Object.freeze({ MIN_PX: 56, RATIO: 1.6 });

/* Did a drag end as a "swipe it away": far enough sideways and clearly more sideways than
   vertical (a stray finger on the way to the tab bar is not an unpin). */
export function swipedAway(dx, dy) {
  const ax = Math.abs(Number(dx) || 0), ay = Math.abs(Number(dy) || 0);
  return ax >= SWIPE.MIN_PX && ax >= ay * SWIPE.RATIO;
}

/* =========================================================================
   loom-phone-core.js — the phone Loom's gesture math (Session P, Stage B2; the page's "Phone:"
   lines -- P1 "swipe the preview to change take; long-press to ★").

   Pure: NO React, no DOM, no window, no fetch, no timers (the long-press timer lives in the
   component; its length is here). Every gesture below only ever names a TAKE NUMBER for the
   existing ★ reducer (selectTakeOnCard -> loom-takes-core.js selectTake): swiping never prices,
   uploads or renders (loom/test/loom-no-auto-render.test.js pins this module and the handlers).
   ========================================================================================= */
import { takesOf, selectedTakeOf } from "./loom-takes-core.js";

/** How far a finger must travel sideways before a swipe counts, and how long a press is long. */
export const SWIPE_MIN_PX = 40;
export const LONG_PRESS_MS = 500;

/**
 * swipeDir(dx, dy) -> +1 (swiped left: the next, newer take), -1 (swiped right: the previous,
 * older take), 0 (not a swipe: too short, or more vertical than sideways -- a scroll).
 */
export const swipeDir = (dx, dy, min = SWIPE_MIN_PX) => {
  const x = Number(dx) || 0, y = Number(dy) || 0;
  if (Math.abs(x) < min || Math.abs(x) <= Math.abs(y) * 1.2) return 0;
  return x < 0 ? 1 : -1;
};

/** The take number a swipe in `dir` lands on, from the ★ take, in number order; null at either
 *  end, for an unrendered shot, or for no direction. Never wraps: a swipe past the last take
 *  does nothing rather than jumping to the first. */
export const adjacentTakeN = (card, dir) => {
  const ts = takesOf(card);
  const sel = selectedTakeOf(card);
  if (!ts.length || sel == null || !dir) return null;
  const i = ts.findIndex((t) => t.n === sel);
  if (i < 0) return null;
  const j = i + (dir > 0 ? 1 : -1);
  return j >= 0 && j < ts.length ? ts[j].n : null;
};

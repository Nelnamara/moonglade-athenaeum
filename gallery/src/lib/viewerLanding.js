/* WHERE THE VIEWER PUTS YOU DOWN (owner, 2026-09-07).

   "When the viewer closes, land on the picture you were viewing; if it is off-page --
   the viewer stepped onto another page -- the top of its page."

   This REFINES "the library stands still" (DECISIONS.md, 2026-09-05), it does not bend
   it. That rule says nothing may move the owner's view of the library except his own
   hands; closing the viewer is his own hands, and the view it hands back was wrong
   before this: the viewer's ← / → step across a page boundary is a real page change
   (App.jsx's userLoad, navRef.want), so a page-7 grid could re-render as page 8 under an
   untouched scroll offset and put him somewhere he had never been.

   The DECISION is here, with no DOM in it, because that is the part worth pinning:
   loom/test/viewer-landing.test.js exercises every outcome without a browser. App.jsx
   owns the measuring and the scrolling.

   The three answers:
     "stay" -- do not touch the scroll. The picture is already fully on screen, or there
               is no card for it to land on (a filter that no longer matches it, a stack
               cover standing in its place) -- and moving to something arbitrary is worse
               than not moving at all.
     "card" -- bring the card the viewer was showing into view, instantly, never smoothly:
               a close is not a journey.
     "top"  -- the top of the page, because the page underneath changed while he was in
               the viewer and there is no "where he was" left on it. */

/** @typedef {"stay"|"card"|"top"} ViewerLanding */

/**
 * @param {object} m
 * @param {boolean} m.pageChanged  the library page at close differs from the one the viewer opened on
 * @param {?number} m.cardTop      the card's top, viewport coordinates; null when it has no card
 * @param {?number} m.cardBottom   the card's bottom, viewport coordinates
 * @param {number}  m.viewportTop  the first y a card can be seen at -- below the sticky chrome
 * @param {number}  m.viewportBottom
 * @returns {ViewerLanding}
 */
export function landingAfterViewer({
  pageChanged, cardTop, cardBottom, viewportTop, viewportBottom,
}) {
  // A changed page wins over everything: whatever the old offset pointed at is gone, and
  // the card measurements (if there even are any) belong to a page he never scrolled.
  if (pageChanged) return "top";
  if (!Number.isFinite(cardTop) || !Number.isFinite(cardBottom)) return "stay";
  // FULLY inside, both edges. Half a card showing is the case this whole ruling exists
  // for -- the picture he was just looking at, cut off at the bottom of the screen.
  if (cardTop >= viewportTop && cardBottom <= viewportBottom) return "stay";
  return "card";
}

export default landingAfterViewer;

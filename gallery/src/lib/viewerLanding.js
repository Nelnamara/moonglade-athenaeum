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

/* WHICH VIEWPORT "ALREADY ON SCREEN" IS MEASURED AGAINST (2026-09-07, correcting the same
   day's build). Three of the four layouts scroll the document, so the window's own
   viewport -- below the sticky chrome -- is the right frame. TIMELINE does not: its cards
   live inside .mgg-tl-cols, a pane with its own overflow-y and its own top and bottom
   edges, and a card can be perfectly "on screen" by the window's reckoning while sitting
   below the fold of the pane that actually holds it.

   Duck-typed on getBoundingClientRect so the window (which has none) falls back to the
   frame the caller measured, and so this is testable without a DOM. */
export function viewportOfScroller(scroller, fallback) {
  if (scroller && typeof scroller.getBoundingClientRect === "function") {
    const r = scroller.getBoundingClientRect();
    if (r && Number.isFinite(r.top) && Number.isFinite(r.bottom)
        && r.bottom > r.top) {
      return { viewportTop: r.top, viewportBottom: r.bottom };
    }
  }
  return fallback;
}

/* SPENDING THE DECISION, in the container that actually scrolls the cards.

   The first build scrolled the WINDOW for the "top" outcome, so in Timeline the ruling did
   nothing at all: the document does not move, and the pane kept the offset it had on the
   page the owner never saw -- exactly the placement this ruling exists to fix.

   "top" moves the scroller itself. "card" goes through the card's own scrollIntoView with
   block:"nearest", which scrolls the nearest scrollable ancestor -- the same pane -- and
   is what lets .mgg-card's scroll-margin-top clear the sticky chrome; hand-rolling that
   offset here would re-implement it and lose the margin.

   Returns what it actually did, which is not always what it was asked to do: a "card"
   landing with no card left to land on is a "stay", the same default the decision itself
   falls back to. */
export function landInScroller(where, { scroller, card, behavior = "instant" } = {}) {
  if (where === "top") {
    if (scroller && typeof scroller.scrollTo === "function") {
      scroller.scrollTo({ top: 0, behavior });
      return "top";
    }
    return "stay";
  }
  if (where === "card" && card && typeof card.scrollIntoView === "function") {
    card.scrollIntoView({ block: "nearest", inline: "nearest", behavior });
    return "card";
  }
  return "stay";
}

export default landingAfterViewer;

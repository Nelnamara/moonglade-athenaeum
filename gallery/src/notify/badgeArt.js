/* One badge <img>'s source ladder: the ANIMATED master first, the still thumb second.

   The move is the toast mascot's, verbatim (ach.js's mascot `chain`, whose comment reads
   "drop <id>.webp beside the stills and it just moves"): ask for the animated file, and on
   its 404 hop to the still. A badge with no animated master 404s once and looks exactly as
   it always did -- an <img> that fails never paints, so the hop is invisible; there is no
   flash and no double-render, only one wasted (local) request.

   What this module adds over a bare inline chain is MEMORY. The mascot chain runs once per
   celebration; badges render by the dozen in the Folio and re-render on every tab, search
   and ladder click. `_start` remembers, per id, which rung actually loaded, so the 404 is
   paid at most once per id per page load and every later mount asks for the still directly.

   Deliberately import-free and DOM-free (it takes the element, it never queries for one) so
   `node --test` can load it as-is -- loom/test/badge-anim-chain.test.js. */

// id -> index into badgeSources() that this page should START at. Only ever moves
// forward (a miss is permanent for the page); never persisted -- a reload is exactly
// when a freshly dropped-in animation should be picked up.
const _start = new Map();

/* The ladder for one badge id, animated first. `size` is the still's cache bucket (the
   toast asks 384 so the enlarged medallion stays crisp; everything else takes the 256
   default) -- it is NOT passed to the animated file, which is served whole, unresized,
   so a size query there would only fragment its cache entry. */
export function badgeSources(id, size) {
  const stem = "/badge-thumb/" + encodeURIComponent(id);
  return [stem + ".webp", stem + ".png" + (size === 384 ? "?size=384" : "")];
}

/* Where this id's <img> should point right now: the animated master until we learn
   this id hasn't got one, the still from then on. */
export function badgeSrc(id, size) {
  return badgeSources(id, size)[_start.get(id) || 0];
}

/* onError handler body: step `img` down to the next rung and report whether there was
   one. `false` means the ladder is exhausted (or the src was never on it -- a masked
   card's mystery art, say) and the CALLER decides what a badge-shaped hole looks like:
   the Folio removes the element, the toast swaps in the emoji. */
export function badgeHop(img, id, size) {
  if (!img) return false;
  const list = badgeSources(id, size);
  // getAttribute, not .src: the property comes back absolutised (http://host/...).
  const i = list.indexOf(img.getAttribute("src") || "");
  if (i < 0 || i + 1 >= list.length) return false;
  if ((_start.get(id) || 0) < i + 1) _start.set(id, i + 1);
  img.src = list[i + 1];
  return true;
}

/* Test seam only -- the memo is page-lifetime state, and a node test needs to prove
   both "remembers a miss" and "starts clean" without a fresh module instance. */
export function _resetBadgeMemo() {
  _start.clear();
}

/* MANUAL ORDER -- the pure half (Session P, P6; Loom Handoff section A's "❖ … · MANUAL ORDER"
   panel and section B's P6 prose; ruling 9).

   P6: a hand-picked collection can hold a manual order. The server stores it
   (collection_order, one position per picture) and answers the collection's members in it
   (ordered_members: the ordered ones by position, then pictures added since, OLDEST first --
   ruling 9). The order editor moves rows with these, then saves the whole list once.

   No React, no DOM, no fetch: the components and api.js do the asking; loom/test pins these. */

/* ---- the order editor ---- */

/** The list with the item at `from` moved to `to` (a drop). Out of range -> the same list. */
export function moveItem(list, from, to) {
  const a = (list || []).slice();
  if (from < 0 || from >= a.length || to < 0 || to >= a.length || from === to) return a;
  const [x] = a.splice(from, 1);
  a.splice(to, 0, x);
  return a;
}

/** ▲ (delta -1) / ▼ (delta +1): the keyboard and button twin of a drag. */
export function moveBy(list, index, delta) {
  return moveItem(list, index, index + delta);
}

/** Has the order changed from what was loaded? */
export function orderChanged(a, b) {
  const x = a || [], y = b || [];
  return x.length !== y.length || x.some((v, i) => v !== y[i]);
}

/** Where a dragged row lands, for moveItem(list, from, <this>): `tops` are the rows' top edges
    (px) in order, `heights` their heights, `y` the pointer, `from` the row being dragged. It is
    the number of OTHER rows whose middle the pointer has passed -- so dragging row 0 down past
    the middle of row 3 lands it at 3 (it takes row 3's place), not at 4. (Counting the dragged
    row's own slot is the off-by-one that dropped a downward drag one place too far.) */
export function dropIndex(tops, heights, y, from = -1) {
  const n = (tops || []).length;
  let at = 0;
  for (let i = 0; i < n; i++) {
    if (i !== from && y > tops[i] + (heights[i] || 0) / 2) at += 1;
  }
  return Math.max(0, Math.min(n - 1, at));
}

/** The editor's status line, in plain words. */
export function orderNote({ manual, count, dirty }) {
  if (dirty) return "Order changed — Save keeps it.";
  if (!count) return "No pictures in this collection yet.";
  return manual
    ? "Saved order. Pictures added later go to the end, oldest first."
    : "No manual order yet — oldest first. Drag (or ▲ ▼) and Save to set one.";
}

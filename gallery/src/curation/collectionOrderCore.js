/* MANUAL ORDER AND "AS SHOTS, IN ORDER" -- the pure half (Session P, P6 and P5; Loom Handoff
   section A's "❖ … · MANUAL ORDER" panel and section B's P5/P6 prose; rulings 9 and 10).

   P6: a hand-picked collection can hold a manual order. The server stores it
   (collection_order, one position per picture) and answers the collection's members in it
   (ordered_members: the ordered ones by position, then pictures added since, OLDEST first --
   ruling 9). The order editor moves rows with these, then saves the whole list once.

   P5: "▮ Send to The Loom · as shots, in order" hands the Loom the pictures IN ORDER --
   the collection's order when the gallery is showing one (restricted to the selection when
   the Actions menu acts on a selection), else the selection oldest first -- through the
   Loom's own address builder, videos left out as "as cast" leaves them out, and REFUSED past
   the one cap (ruling 10), never silently cut.

   No React, no DOM, no fetch: the components and api.js do the asking; loom/test pins these. */

import { buildLoomUrl, SHOTS_HANDOFF_CAP } from "../../../loom/src/loom-url.js";

export { SHOTS_HANDOFF_CAP };
/** What `from` says when the pictures were a plain selection (the Loom names the act so). */
export const FROM_SELECTION = "your selection";

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

/* ---- "as shots, in order" ---- */

/**
 * The ids to send, in order.
 *   selection  the ids the Actions menu acts on (none -> the whole `ordered` list)
 *   ordered    the collection's members in ITS order (GET /api/collections/order), or null
 *              when the gallery is not showing a collection
 *   dated      {id: created_at} for the selection -- the date order, oldest first, for a
 *              plain selection and for any selected picture the order does not list
 */
export function shotsOrder({ selection, ordered, dated } = {}) {
  const sel = Array.from(selection || []).map(String);
  const when = dated || {};
  const byDate = (ids) => ids.slice().sort((a, b) => {
    const x = String(when[a] || ""), y = String(when[b] || "");
    return x < y ? -1 : x > y ? 1 : (a < b ? -1 : a > b ? 1 : 0);
  });
  if (!ordered) return byDate(sel);
  const list = ordered.map(String);
  if (!sel.length) return list;
  const want = new Set(sel);
  const inOrder = list.filter((id) => want.has(id));
  const listed = new Set(list);
  return inOrder.concat(byDate(sel.filter((id) => !listed.has(id))));
}

/**
 * shotsSend({ids, videos, from, nonce, cap}) -> {ok: true, ids, href} | {ok: false, error}
 * Videos are left out (only pictures become shots, as "as cast" sends pictures only). More
 * than the cap is refused with a message naming it -- nothing is sent and nothing is cut.
 */
export function shotsSend({ ids, videos, from, nonce, cap = SHOTS_HANDOFF_CAP } = {}) {
  const vids = videos instanceof Set ? videos : new Set(videos || []);
  const seen = new Set();
  const keep = (ids || []).map(String).filter((id) => id && !vids.has(id) && !seen.has(id) && seen.add(id));
  if (!keep.length) {
    return { ok: false, error: "Only pictures become shots, and there are none to send here. Nothing was sent." };
  }
  if (keep.length > cap) {
    return { ok: false, error: "That's " + keep.length + " pictures. The Loom takes at most " + cap
      + " at once as shots — send a smaller selection or collection. Nothing was sent." };
  }
  const name = String(from || "").trim() || FROM_SELECTION;
  return { ok: true, ids: keep, href: buildLoomUrl({ shots: keep.join(","), from: name, n: String(nonce || "") }, "", "/loom") };
}

/** A fresh nonce from a random source the caller supplies (Math.random in the app). */
export function shotsNonce(rand) {
  const r = typeof rand === "function" ? rand : Math.random;
  return (Math.floor(r() * 36 ** 6).toString(36) + Math.floor(r() * 36 ** 6).toString(36)).slice(0, 12) || "n";
}

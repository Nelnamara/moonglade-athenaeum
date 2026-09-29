/* "▮ SEND TO THE LOOM" -- the two choices (Session P, P5; Loom Handoff section B's P5 prose).

   "as cast" is today's hand-off, unchanged: the pictures become @image cast members
   (/loom?cast=). "as shots, in order" makes a new act of image-to-video shots, one per picture,
   in the collection's order -- through the Loom's own address builder, with a nonce so a reload
   never adds the act twice. Both leave videos out. Neither prices, submits or renders anything:
   they only navigate to the Loom, which asks once before it changes a board.

   The deciding is collectionOrderCore.js's (pure, tested); this file only asks the server the
   two read-only questions it needs: the collection's order, and each picture's date and kind. */

import { fetchCollectionOrder, fetchPictureFacts } from "../api.js";
import { FROM_SELECTION, shotsNonce, shotsOrder, shotsSend } from "./collectionOrderCore.js";

/** -> {ok, href, ids} | {ok: false, error}. `collection` = the collection the gallery is
    showing (hand-picked or smart), or "" for none; `ids` = the selection (or, from the order
    editor, the collection's pictures in the order on screen, with `ordered` given). */
export async function planShotsSend({ ids, collection, ordered }) {
  let order = ordered || null;
  if (!order && collection) {
    const d = await fetchCollectionOrder(collection);
    if (d && !d.error && Array.isArray(d.media_ids)) order = d.media_ids;
  }
  const facts = await fetchPictureFacts(ids);
  const dated = {}, videos = new Set();
  Object.keys(facts).forEach((id) => {
    dated[id] = facts[id].created_at || "";
    if (facts[id].is_video) videos.add(id);
  });
  const inOrder = shotsOrder({ selection: ids, ordered: order, dated });
  return shotsSend({ ids: inOrder, videos, from: collection || FROM_SELECTION, nonce: shotsNonce() });
}

/** "as cast" for a whole collection's pictures (the order editor's second button): today's
    /loom?cast= hand-off, videos left out. -> {ok, href} | {ok: false, error}. */
export async function planCastSend(ids) {
  const facts = await fetchPictureFacts(ids);
  const keep = Array.from(ids || []).map(String).filter((id) => !(facts[id] && facts[id].is_video));
  if (!keep.length) return { ok: false, error: "Only pictures join the cast, and there are none to send here." };
  return { ok: true, href: "/loom?cast=" + encodeURIComponent(keep.join(",")) };
}

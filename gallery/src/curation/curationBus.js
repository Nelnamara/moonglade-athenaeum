/* One event, "the server changed some pictures' curation state".

   The library page (App's items) is patched by useCurate directly, but two other places hold
   their own copy of a picture's values: the open Details record (useImageDetails fetches the
   row once and mirrors it) and its "Your layer" card. Both listen here, so a rating pressed
   on the keyboard, a bulk keeper mark and an Undo all reach the record that is open without
   it re-fetching and without a prop chain from the shell down into it.

   detail.after is the server's {media_id: {rating, mark, tags, note}} for the pictures that
   changed (or were put back). */
export const CURATED_EVENT = "mg-curated";

export function announceCurated(after) {
  if (typeof window === "undefined" || !after || !Object.keys(after).length) return;
  window.dispatchEvent(new CustomEvent(CURATED_EVENT, { detail: { after } }));
}

/* Subscribe; returns the unsubscribe. */
export function onCurated(fn) {
  if (typeof window === "undefined") return () => {};
  const h = (e) => fn((e.detail && e.detail.after) || {});
  window.addEventListener(CURATED_EVENT, h);
  return () => window.removeEventListener(CURATED_EVENT, h);
}

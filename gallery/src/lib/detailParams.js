/* The filter set the picture page (Details) sends to /api/detail/<mid>.

   /api/detail answers with the picture's place in the SAME filtered, sorted walk the library list
   shows -- `position`, `nav_total`, `prev_id`, `next_id` -- so it must be told every filter the list
   was asked with. The list's own parameter names are used here (the library's pageQuery in
   hooks/useLibrary.js), minus paging.

   `batch` is the View batch drill-down (a task id): without it the picture page counted the whole
   library and Prev/Next stepped out of the batch (#81). `series` is the same thing for an opened
   stack (?series=<sid>, which /api/library honours): without it a picture opened inside one counted
   the whole library too. One builder, so the desktop shell (App.jsx) and the phone shell
   (AppMobile.jsx) cannot drift apart again.

   `stack` is the stack the open picture was opened FROM (the desktop's stack modal, which
   deliberately leaves adv alone so the library behind it does not move): { kind: "series" | "batch",
   id } as detailStackOf reads it off the modal. A series stack sends `series`, a batch stack sends
   `batch` (its task id), never both, and either one wins over whatever adv holds for this request
   only. With no stack (opened from the grid) adv's own batch / series ride as before.

   Empty values are dropped by the caller (useImageDetails skips falsy entries), so a blank filter
   costs nothing on the wire. The caller must memoize the result on the real values: the fetch
   effect depends on this object by reference (see the 2026-08-04 note in App.jsx). */
export function detailAdvParams({ applied, media, shelf, adv, stack }) {
  const a = adv || {};
  const s = detailStackOf(stack);
  return {
    q: applied, media, collection: shelf,
    sort: a.sort !== "newest" ? a.sort : "", rating_min: a.ratingMin || "",
    model: a.model, lora: a.lora, from: a.dateFrom, to: a.dateTo,
    source: a.source, tag: a.tag, published: a.publishedOnly ? "1" : "",
    batch: s ? (s.kind === "batch" ? s.id : "") : a.batch,
    series: s ? (s.kind === "series" ? s.id : "") : a.series,
  };
}

/* The scope an opened stack gives the picture page: { kind, id } with a string id, or null (no stack,
   a kind that is neither, or no id). A series stack's id is its sid (-> `series`); a batch stack's is
   its task id (-> `batch`). */
export function detailStackOf(stack) {
  if (!stack || !stack.id) return null;
  if (stack.kind !== "series" && stack.kind !== "batch") return null;
  return { kind: stack.kind, id: String(stack.id) };
}

/* One row per model, always.

   PixAI's ranking feeds repeat a model across page boundaries -- measured live on the dev server
   2026-09-07: twelve trending LoRA pages, 288 rows, 281 distinct ids, repeats on pages 2, 4, 7
   and 12. The picker keys each card on model_id, and React cannot cope with a repeated key: the
   card behind the repeat is silently dropped from its bookkeeping, so on the next fresh list React
   cannot remove it again and it stays in the grid, at the top, on top of every later result. Each
   search left a few more behind. That leftover pile was the owner's "it's always the SAME LoRA"
   and "search is still shit" (2026-09-07): the real results were there, underneath.

   Vanilla JS never had this problem -- it rewrote the grid wholesale -- which is why the picker
   "worked" until 2026-08-08. The fix is where the rows are assembled: a fresh page is deduped, a
   continuation only adds ids the list does not already hold. Rows without an id are kept (there is
   nothing to collide on) and the component gives them a positional key instead. */

export function rowKey(row) {
  return row && row.model_id != null && row.model_id !== "" ? String(row.model_id) : "";
}

/* A fresh list: keep the first occurrence of every id, in order. */
export function uniqueRows(rows) {
  const seen = new Set();
  const out = [];
  for (const r of rows || []) {
    const k = rowKey(r);
    if (k) {
      if (seen.has(k)) continue;
      seen.add(k);
    }
    out.push(r);
  }
  return out;
}

/* A continuation: `old` plus the incoming rows whose id `old` (or an earlier incoming row) does
   not already carry. Returns `old` itself when nothing is new, so React sees no change. */
export function appendRows(old, incoming) {
  const base = old || [];
  const seen = new Set();
  for (const r of base) {
    const k = rowKey(r);
    if (k) seen.add(k);
  }
  const fresh = [];
  for (const r of incoming || []) {
    const k = rowKey(r);
    if (k) {
      if (seen.has(k)) continue;
      seen.add(k);
    }
    fresh.push(r);
  }
  return fresh.length ? base.concat(fresh) : base;
}

/* The nearest ancestor that scrolls -- the element an IntersectionObserver must use as its root
   for a margin to mean "this far before the end of the LIST". With root:null the margin widens the
   viewport, but a clipping ancestor still clips first, so a sentinel inside a scrolling pane only
   ever intersects once it is physically on screen: no head start, a full server round trip (0.6 to
   0.9 s per page, measured) spent staring at the bottom of the list on every page. Null when nothing
   between the element and <body> scrolls, in which case the viewport is the right root. */
export function scrollParentOf(el) {
  let e = el && el.parentElement;
  while (e && e !== document.body) {
    const oy = getComputedStyle(e).overflowY;
    if (oy === "auto" || oy === "scroll") return e;
    e = e.parentElement;
  }
  return null;
}

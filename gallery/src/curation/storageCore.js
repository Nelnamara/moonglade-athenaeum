/* THE STORAGE BARS, CLIENT HALF (Session N6) -- what the screens decide about Collection
   Health's three stacked bars without React or a DOM. The numbers are the server's (the
   `storage` block of GET /api/health, moonglade_gallery.storage_breakdown); this turns them
   into segments (widths, hues, titles) and into the filter a click opens. Desktop and phone
   draw the SAME rows, so it is one module. loom/test/storage-core.test.js pins it.

   THE TYPE HUES FOLLOW THE SELECTED SKIN, except one (the owner's ruling, 2026-09-29): images
   take the skin's accent (--accent, the token every skin redefines), video takes a second tone
   derived from that same accent (the accent mixed toward the page's own ground, so it is the
   same hue, plainly darker), and Loom renders are ALWAYS the Loom's own cyan (--loomc: cyan
   means the Loom in every skin, and no skin ever changes it). Gold is billing only and is never
   used on these bars. They are the app's tokens, never hexes. Models fade lavender (a skin token
   too) toward the deep violet; collections cycle accent, cyan, mauve and emerald at a lower strength
   than the type hues, so no collection reads as "a type". */

export const TYPE_HUES = {
  image: "var(--accent)",
  video: "color-mix(in oklab, var(--accent) 50%, var(--base))",
  loom: "var(--loomc)",
};

const MODEL_HUES = [
  "var(--lavender)",
  "color-mix(in oklab, var(--lavender) 70%, var(--purple-bright))",
  "color-mix(in oklab, var(--lavender) 45%, var(--purple-bright))",
  "color-mix(in oklab, var(--lavender) 25%, var(--purple-bright))",
];
const COLLECTION_HUES = [
  "color-mix(in oklab, var(--accent) 62%, var(--base))",
  "color-mix(in oklab, var(--loomc) 55%, var(--base))",
  "color-mix(in oklab, var(--mauve) 55%, var(--base))",
  "color-mix(in oklab, var(--emerald) 50%, var(--base))",
];
const OTHER_HUE = "var(--surface1)";

/* Bytes in the words the rest of Health uses ("4.8 MB"). The server sends `h` on every segment;
   this is for a total the client adds up itself. */
export function fmtBytes(n) {
  let v = Math.max(0, Number(n) || 0);
  for (const u of ["B", "KB", "MB", "GB"]) {
    if (v < 1024) return v.toFixed(u === "B" ? 0 : 1) + " " + u;
    v /= 1024;
  }
  return v.toFixed(1) + " TB";
}

const count = (n) => Number(n || 0).toLocaleString();

/* One segment: {key, label, title, hue, pct, bytes, filter}. `pct` is its share of the bar's
   own total, 0-100. `filter` is what a click opens, or null (Other has no filter: it is
   "everything not named above", which no search says). */
function seg(label, s, hue, of, filter, key) {
  return {
    key, label, hue, bytes: s.bytes, filter,
    pct: of > 0 ? (s.bytes / of) * 100 : 0,
    title: label + " · " + s.h + " · " + count(s.count) + (s.count === 1 ? " picture" : " pictures"),
  };
}

/* The three bars from the payload's `storage` block, or [] when there is none (an older server,
   or a library with nothing on disk). Each bar: {id, label, note?, total, segments}. Segments
   with no bytes are dropped: a zero-width segment is a legend entry that opens an empty page. */
export function storageBars(storage) {
  if (!storage || !(storage.total_bytes > 0)) return [];
  const total = storage.total_bytes;
  const keep = (segs) => segs.filter((s) => s.bytes > 0);
  const byType = keep(storage.by_type || []).map((s) =>
    seg(s.name, s, TYPE_HUES[s.key] || OTHER_HUE, total, { kind: "type", value: s.key }, s.key));
  const byModel = (storage.by_model || []).filter((s) => s.bytes > 0).map((s, i) => seg(
    s.name, s, s.other ? OTHER_HUE : MODEL_HUES[i % MODEL_HUES.length], total,
    s.other ? null : { kind: "model", value: s.name }, "m" + i));
  const coll = storage.by_collection || { segments: [], sum_bytes: 0 };
  const byColl = (coll.segments || []).filter((s) => s.bytes > 0).map((s, i) => seg(
    s.name, s, s.other ? OTHER_HUE : COLLECTION_HUES[i % COLLECTION_HUES.length], coll.sum_bytes,
    s.other ? null : { kind: "collection", value: s.name }, "c" + i));
  const bars = [
    { id: "type", label: "BY TYPE", total, segments: byType },
    { id: "model", label: "BY MODEL", total, segments: byModel },
  ];
  if (byColl.length) {
    bars.push({ id: "collection", label: "BY COLLECTION", note: "can overlap", total: coll.sum_bytes, segments: byColl });
  }
  return bars.filter((b) => b.segments.length);
}

/* What a segment's click asks the library for, as the patch the gallery's own filter path takes
   (applyAdvanced): the whole filter set starts over (the bars measure the whole library, so a
   segment opens "all of this", not "this within whatever was filtered"), then the one filter.
   A type is a search operator (`type:video`), a model is the Model filter, a collection is the
   shelf. Returns null for a segment with no filter. */
export function storageFilterPatch(filter) {
  if (!filter) return null;
  if (filter.kind === "type") return { q: "type:" + filter.value, model: "", shelf: "", media: "" };
  if (filter.kind === "model") return { q: "", model: filter.value, shelf: "", media: "" };
  if (filter.kind === "collection") return { q: "", model: "", shelf: filter.value, media: "" };
  return null;
}

import { useSwrGet } from "./swrCache.js";

/* useHealth -- HealthOverlay.jsx's fetch/state/derivation, mechanically
   lifted out (2026-08-03), same precedent as useMyArt.js/useContests.js/
   useImport.js this pass (see useMyArt.js's header comment for the full
   "ONE place this state has ever lived, refactored to CONSUME rather than
   duplicate" rationale). HealthOverlay.jsx is refactored to CONSUME this
   hook; the new mobile Health screen (HealthMobile.jsx) gets the identical
   stats/bars/chips data, not a second fetch of GET /api/health.

   What deliberately did NOT move here, matching useControlPanel.js's own
   documented split for `tab`/`subOverlay`: the model/tag/LoRA filter
   callbacks and the Duplicate Review hookup (onModelFilter/onTagFilter/
   onLoraFilter/onOpenDuplicates) stay props each CONSUMER wires its own way
   -- desktop closes its overlay and calls App.jsx's applyAdvanced() directly;
   mobile applies through the lifted useLibrary() instance, switches to the
   Gallery tab, and closes the pushed screen (see AppMobile.jsx). WHAT a
   filter tap does next is a presentation decision, not hook internals. */

export const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString());

// Stale-while-revalidate (owner report 2026-08-06: the panel was "VERY slow" at 35k
// images). The last payload survives across opens for the whole page session; a reopen
// renders those numbers INSTANTLY while the refetch replaces them in place. First open
// still waits (nothing to show yet) -- that first wait is what the server-side walk
// rewrite + api_health's memo attack.
//
// This file's own `_lastHealth` module variable WAS that cache, alone, for every overlay in
// the app (2026-09-04): it is now hooks/swrStore.js's map, and this hook is one ordinary
// consumer of it -- same mechanism, same wording above, one implementation. The one
// behavioural difference is the shared rule's, and it is the better answer: a failed
// REFRESH no longer reports an error over numbers that are seconds old (HealthMobile.jsx
// returns early on `err` and would have replaced a full screen of good stats with one
// error line). Nothing cached still surfaces the error exactly as before.
export default function useHealth() {
  const { data: h, err } = useSwrGet("/api/health");

  // Stats tiles: real fields from collection_health(), the full 12-tile set
  // HealthOverlay.jsx already shows on desktop (gold = the celebration
  // numbers; dup = the clickable Duplicate pair on desktop -- see
  // HealthMobile.jsx's own header comment for why mobile renders those two
  // as plain, non-clickable tiles this pass instead).
  // Frontend Gallery.dc.html's HEALTH_STATS (search that name) is the real order + the
  // real gold flag: Duplicates/Reclaimable sit at positions 9-10 (not last), only
  // Uncataloged is gold (was Published+Total likes instead, an unrelated substitution),
  // and 3 labels drifted from the design's own wording ("Storage used"/"Model known", not
  // "Library size"/"Model named" -- "Full-meta", not "Full metadata", matched verbatim even
  // though it reads a little terse, since that's the design's own literal string).
  const stats = h ? [
    { label: "Images on disk", value: fmt(h.total_files) },
    { label: "Storage used", value: h.total_size_h || "—" },
    { label: "Catalog rows", value: fmt(h.catalog_rows) },
    { label: "Full-meta", value: (h.full_meta_pct != null ? h.full_meta_pct + "%" : "—") },
    { label: "Model known", value: (h.model_pct != null ? h.model_pct + "%" : "—") },
    { label: "Rated", value: fmt(h.rated) },
    { label: "Published", value: fmt(h.published) },
    { label: "Total likes", value: fmt(h.total_likes) },
    { label: "Duplicates", value: fmt(h.dup_redundant), dup: true },
    { label: "Reclaimable", value: h.dup_bytes_h || "—", dup: true },
    { label: "Missing files", value: fmt(h.missing) },
    { label: "Uncataloged", value: fmt(h.uncataloged), gold: true },
  ] : [];

  const monthMax = h && h.by_month && h.by_month.length
    ? Math.max(...h.by_month.map((m) => m[1])) : 1;
  const modelMax = h && h.top_models && h.top_models.length
    ? Math.max(...h.top_models.map((m) => m[1])) : 1;

  // Word-cloud tiers by rank, matching the DC's three visual weights (desktop
  // only -- see HealthMobile.jsx's header comment for why the word cloud
  // itself is scoped out of this mobile pass).
  const tier = (i) => (i < 4 ? "t1" : i < 12 ? "t2" : "t3");

  const buckets = h && h.per_bucket ? Object.entries(h.per_bucket) : [];

  return { h, err, stats, monthMax, modelMax, tier, buckets };
}

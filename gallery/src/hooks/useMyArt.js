import { useSwrGet } from "./swrCache.js";

/* useMyArt -- MyArtOverlay.jsx's fetch/state/derivation, mechanically lifted
   out (2026-08-03) into its own hook so a new mobile screen can consume the
   EXACT same data/logic instead of a second, drifting fetch of
   GET /api/your-art. Matches the useLibrary.js/useControlPanel.js precedent
   this session already set twice (see those files' own header comments):
   MyArtOverlay.jsx -- the ONE place this state has ever lived -- is
   refactored to CONSUME this hook rather than left holding a second copy,
   and the new mobile screen (MyArtMobile.jsx) consumes the exact same hook
   instance-per-mount, never a reimplementation of its own.

   A byte-for-byte copy of the fetch effect + stats/maxViews derivations that
   used to live inline in MyArtOverlay.jsx's component body -- not a rewrite. */

export const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString());

// Stale-while-revalidate through the shared read cache (hooks/swrCache.js), the same
// mechanism useHealth.js has used since 2026-08-06 and every nav overlay now shares:
// a REOPEN paints the last totals/rows in the first frame and swaps in the fresh answer
// behind. The mutation seams that must NOT show a stale answer -- App.jsx's afterMutation
// and MyArtOverlay's own confirm/confirmBulk -- invalidate("/api/your-art") explicitly.
export default function useMyArt() {
  const { data: d, err } = useSwrGet("/api/your-art");

  const totals = d ? d.totals || {} : {};
  const items = d ? d.items || [] : [];
  // Frontend Gallery.dc.html:2425-2426 -- design order is PUBLISHED, VIEWS (accent-
  // highlighted), LIKES, COMMENTS; was PUBLISHED, LIKES, COMMENTS, VIEWS with no accent.
  const stats = d ? [
    { value: fmt(totals.count), label: "PUBLISHED" },
    { value: d.views_synced ? fmt(totals.views_top) : "—", label: "VIEWS (TOP " + items.length + ")", accent: true },
    { value: fmt(totals.likes), label: "TOTAL LIKES" },
    { value: fmt(totals.comments), label: "COMMENTS" },
  ] : [];

  const maxViews = items.length ? Math.max(1, ...items.map((r) => r.views || 0)) : 1;

  return { d, err, totals, items, stats, maxViews };
}

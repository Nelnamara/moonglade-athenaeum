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

  // THE VIEWS STAT IS A REAL LIFETIME TOTAL AS OF 2026-09-06. It used to read
  // "VIEWS (TOP 12)" because that is genuinely all it could say: views were fetched live,
  // twelve calls per open, so there was no number for the other ninety-odd works. Views
  // now ride --sync-artworks into a catalog column, so the sum is the whole published
  // library. The label still carries the caveat when there is one -- a partly-swept
  // library says so in the label rather than presenting a subtotal as a total, which is
  // exactly the job the old "(TOP 12)" was doing.
  const swept = totals.views_rows || 0;
  const published = totals.count || 0;
  const viewsLabel = !d || !d.views_synced ? "TOTAL VIEWS"
    : swept < published ? "VIEWS (" + swept + " OF " + published + ")"
      : "TOTAL VIEWS";
  // Frontend Gallery.dc.html:2425-2426 -- design order is PUBLISHED, VIEWS (accent-
  // highlighted), LIKES, COMMENTS; was PUBLISHED, LIKES, COMMENTS, VIEWS with no accent.
  const stats = d ? [
    { value: fmt(totals.count), label: "PUBLISHED" },
    { value: d.views_synced ? fmt(totals.views) : "—", label: viewsLabel, accent: true },
    { value: fmt(totals.likes), label: "TOTAL LIKES" },
    { value: fmt(totals.comments), label: "COMMENTS" },
  ] : [];

  // The comparison bar's denominator. Unchanged in shape from the original ranked list
  // (commit cecdd91f) -- what changed is that `items` is no longer a hardcoded twelve, so
  // the bar is now relative to the owner's real best rather than to the best of a dozen.
  const maxViews = items.length ? Math.max(1, ...items.map((r) => r.views || 0)) : 1;

  return { d, err, totals, items, stats, maxViews,
           viewsSynced: !!(d && d.views_synced),
           spikes: (d && d.spikes) || [],
           viewsAt: (d && d.views_at) || "" };
}

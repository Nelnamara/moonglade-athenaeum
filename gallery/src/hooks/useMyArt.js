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

/* WHY MY ART IS EMPTY, WHEN THE ANSWER IS "the sync has never run" (#42, 2026-09-06).

   My Art is a pure catalog read: /api/myart/items returns the rows carrying an
   artwork_id, and artwork_id / is_published are written EXCLUSIVELY by --sync-artworks
   (moonglade_backup.py's run_sync_artworks). So a library that has never been synced
   answers with exactly the same zero rows as one that has genuinely published nothing,
   and the empty state used to say the same "Nothing here yet." to both -- silence, in
   front of a fix that is one Control Panel action away.

   The check is deliberately narrow, so the surface can never blame a sync for something
   else. All three have to hold:
     - there are no artwork rows AT ALL (`rows`, not the tab's filtered `media`: an
       Animations tab with no videos, or a Visibility filter with no matches, is empty
       for its own perfectly ordinary reason and keeps the plain line)
     - the catalog holds media, so there was something to sync
     - the sync's own column is empty across the whole catalog
   `coverage` rides along on /api/myart/items (moonglade_gallery.py's myart_coverage).
   A response from before that field existed, or a soft failure, leaves it absent -- and
   an absent coverage claims nothing, which is the old behaviour exactly. */
export function artworksNeverSynced(rows, coverage) {
  if (!rows || rows.length) return false;
  const c = coverage || {};
  return (c.media || 0) > 0 && (c.artworks || 0) === 0;
}

/* One wording, both shells -- the desktop overlay and the phone screen render their own
   markup (mgma2-* vs myam-*) but must not drift on WHAT they tell the owner. Names the
   real screen and the real button: Control Panel -> Maintenance -> "Check — read-only" ->
   "Sync published-artwork metadata" (ControlPanelOverlay.jsx, ControlMobile.jsx), with the
   command-line equivalent for a library tended from a terminal. */
export const NEVER_SYNCED_WHY =
  "Published-artwork details have never been synced into this library, so there is nothing "
  + "here to list — the titles, tags, likes and comments this gallery reads all arrive with "
  + "that sync. Run “Sync published-artwork metadata” in the Control Panel, under "
  + "Maintenance, or pass --sync-artworks on the command line, then reopen this.";

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

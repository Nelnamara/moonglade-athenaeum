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

  // THE VIEWS STAT IS A REAL LIFETIME TOTAL AS OF 2026-09-06. It used to read
  // "VIEWS (TOP 12)" because that is genuinely all it could say: views were fetched live,
  // twelve calls per open, so there was no number for the other ninety-odd works. Views
  // now ride --sync-artworks into a catalog column, so the sum is the whole published
  // library. The label still carries the caveat when there is one -- a partly-swept
  // library says so in the label rather than presenting a subtotal as a total, which is
  // exactly the job the old "(TOP 12)" was doing.
  const swept = totals.views_rows || 0;
  const published = totals.count || 0;
  const viewsLabel = !d || !d.views_synced ? "Total views"
    : swept < published ? "Views (" + swept + " of " + published + ")"
      : "Total views";
  // Frontend Gallery.dc.html:2425-2426 -- design order is PUBLISHED, VIEWS (accent-
  // highlighted), LIKES, COMMENTS; was PUBLISHED, LIKES, COMMENTS, VIEWS with no accent.
  const stats = d ? [
    { value: fmt(totals.count), label: "Published" },
    { value: d.views_synced ? fmt(totals.views) : "—", label: viewsLabel, accent: true },
    { value: fmt(totals.likes), label: "Total likes" },
    { value: fmt(totals.comments), label: "Comments" },
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

/* THE ALL TIME / 30 DAYS SWITCH (owner pick, look board round 2 topic 6 option A, 2026-11-19).
   One pure set of helpers for both shells, so the desktop overlay and the phone screen cannot
   drift on WHAT the switch counts.

   /api/myart/items carries per-work `views_30` / `likes_30` (the gain since a baseline snapshot)
   and a `window` {days, since, full, seen}. The app only began keeping daily readings the day
   this shipped, so until 30 days of them exist the "30 days" is honestly "since <date>": the
   label says so (windowTag) and the switch itself stays "30 days" -- the owner's own words. */
export const SPAN_OPTS = [["all", "All time"], ["30", "30 days"]];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const shortDay = (iso) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? MONTHS[Number(m[2]) - 1] + " " + Number(m[3]) : "";
};

/* "30 days" once the history reaches back that far, else "since Nov 19". */
export function windowTag(win) {
  if (!win || win.full) return "30 days";
  return win.since ? "since " + shortDay(win.since) : "30 days";
}

/* A work's number under the chosen span: lifetime, or its gain in the window. null stays null
   (views never swept is not a zero). */
export const spanViews = (r, span) => (span === "30" ? (r.views_30 == null ? null : r.views_30) : r.views);
export const spanLikes = (r, span) => (span === "30" ? (r.likes_30 || 0) : r.likes);

/* The stat row under the switch: Published and Comments stay lifetime (the mock leaves them);
   Views and Likes become the window's totals over the published works. `stats` is useMyArt's
   own array -- index 1 views, index 2 likes -- so the all-time row is unchanged. */
export function spanStats(stats, rows, win, span) {
  if (span !== "30" || !stats || !stats.length) return stats;
  const pub = (rows || []).filter((r) => r.public);
  const viewed = pub.filter((r) => r.views_30 != null);
  const tag = windowTag(win);
  const out = stats.slice();
  out[1] = { ...stats[1], value: viewed.length ? fmt(viewed.reduce((s, r) => s + r.views_30, 0)) : "—",
    label: "Views, " + tag };
  out[2] = { ...stats[2], value: fmt(pub.reduce((s, r) => s + (r.likes_30 || 0), 0)),
    label: "Likes, " + tag };
  return out;
}

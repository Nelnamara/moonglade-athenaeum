import { useEffect, useState } from "react";

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

export default function useMyArt() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let dead = false;
    fetch("/api/your-art")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((data) => { if (!dead) setD(data); })
      .catch((e) => { if (!dead) setErr(String(e.message || e)); });
    return () => { dead = true; };
  }, []);

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

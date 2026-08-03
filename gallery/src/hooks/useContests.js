import { useEffect, useState } from "react";

/* useContests -- ContestsOverlay.jsx's fetch/state/derivation, mechanically
   lifted out (2026-08-03), same precedent as useMyArt.js/useHealth.js/
   useImport.js this pass (see useMyArt.js's header comment). ContestsOverlay.jsx
   is refactored to CONSUME this hook; the new mobile Contests screen
   (ContestsMobile.jsx) gets the identical official/community split and
   openContest()/dateRange() logic, not a second fetch of GET /api/contests. */

export const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString());

export default function useContests() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let dead = false;
    fetch("/api/contests")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((data) => { if (!dead) setD(data); })
      .catch((e) => { if (!dead) setErr(String(e.message || e)); });
    return () => { dead = true; };
  }, []);

  const contests = d ? d.contests || [] : [];
  const official = contests.filter((c) => c.type === "official");
  const community = contests.filter((c) => c.type !== "official");
  const featured = official[0];
  const restOfficial = official.slice(1);

  const openContest = (row) => { if (row.url) window.open(row.url, "_blank", "noopener"); };

  const dateRange = (row) => {
    const s = (row.start_at || "").slice(0, 10);
    const e = (row.end_at || "").slice(0, 10);
    return s && e ? s + " – " + e : s || e || "";
  };

  // Mobile-only convenience -- classic's own daysLeft() helper
  // (moonglade_gallery.py) ported here so the mobile Contests screen can show
  // the design mock's compact "N days left" shape for community cards
  // instead of the desktop overlay's literal date range, WITHOUT inventing a
  // field the real payload doesn't have (only start_at/end_at ISO dates
  // exist). Not used by ContestsOverlay.jsx -- desktop keeps rendering
  // dateRange() for every card, unchanged.
  const daysLeft = (row) => {
    if (!row.end_at) return "";
    const end = new Date(row.end_at).getTime();
    if (Number.isNaN(end)) return "";
    const days = Math.ceil((end - Date.now()) / 86400000);
    if (days < 0) return "ended";
    if (days === 0) return "ends today";
    return days + (days === 1 ? " day left" : " days left");
  };

  return { d, err, contests, official, community, featured, restOfficial, openContest, dateRange, daysLeft };
}

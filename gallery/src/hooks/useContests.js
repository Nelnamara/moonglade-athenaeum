import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiPost } from "../api.js";
import { localDay } from "../gen/dates.js";

/* useContests -- ContestsOverlay.jsx's fetch/state/derivation, mechanically
   lifted out (2026-08-03), same precedent as useMyArt.js/useHealth.js/
   useImport.js this pass (see useMyArt.js's header comment). ContestsOverlay.jsx
   is refactored to CONSUME this hook; the new mobile Contests screen
   (ContestsMobile.jsx) gets the identical official/community split and
   openContest()/dateRange() logic, not a second fetch of GET /api/contests.

   2026-08-31, the contest workbench: the entries half (GET /api/contest/mine +
   the one fire-and-forget POST /api/contest/sync on open) is OPT-IN via
   useContests({ mine: true }). Desktop asks for it; ContestsMobile's bare
   useContests() call makes not one extra request, which is what keeps the
   mobile surface genuinely untouched by this pass rather than untouched-looking. */

export const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString());

/* ---- dates, one implementation ------------------------------------------------
   Every count/date/countdown in the contest frames is ui-monospace + tabular-nums;
   these produce the STRINGS those slots render. */

// The DISPLAY day for a contest date. Was a raw slice(0,10) -- i.e. the UTC day -- so a
// deadline read one day early for anyone west of Greenwich, disagreeing with the Grid and
// the Details view, which have used localDay for exactly this reason for a while. Same
// helper, so all three now say the same date about the same instant. (A bare "2026-09-20"
// passes through untouched: it is already a day, with no zone to convert.)
export const dayOf = (iso) => localDay(iso);

export function tsOf(iso) {
  const t = Date.parse(String(iso || ""));
  return Number.isNaN(t) ? null : t;
}

/* The §8.4 countdown. Outside 48h: "12d 04h". Inside 48h it goes HOUR-precise
   ("in 31h 12m") and the caller paints it gold -- no pulse, no motion; gold is
   already the surface's word for "worth attention". Past its date -> {over}. */
export function countdown(iso, now) {
  const t = tsOf(iso);
  if (t === null) return null;
  const left = t - (now == null ? Date.now() : now);
  if (left <= 0) return { text: "", hot: false, over: true };
  if (left < 48 * 3600000) {
    const h = Math.floor(left / 3600000);
    const m = Math.floor((left - h * 3600000) / 60000);
    return { text: "in " + h + "h " + String(m).padStart(2, "0") + "m", hot: true, over: false };
  }
  const d = Math.floor(left / 86400000);
  const h = Math.floor((left - d * 86400000) / 3600000);
  return { text: d + "d " + String(h).padStart(2, "0") + "h", hot: false, over: false };
}

/* Is this contest still open to entries? `active` is the server's own
   runtimeStatus=='running' -- no client-side date math decides it. */
export const isRunning = (c) => !!(c && c.active);

/* Best-effort eligibility, the client half of the "publishedAt > startAt" rule.
   GROUNDED, and the grounding matters: the catalog carries NO artwork publish
   date -- --sync-artworks stores no createdAt for an artwork -- so the only date
   an owned piece has is when it was GENERATED. That is a fair proxy (art is
   published at or after it is made) but it is a proxy, so the label under a tile
   says "made", never "published", and PixAI's own NOT_ELIGIBLE is the real gate. */
export function qualifies(item, contest) {
  if (!item || !contest || !contest.active) return false;
  if (!item.artwork_id || !item.public) return false;
  const start = tsOf(contest.start_at);
  const made = tsOf(item.created_at);
  if (start === null || made === null) return true;      // undated: let the server decide
  return made > start;
}

export default function useContests(opts) {
  const wantMine = !!(opts && opts.mine);
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let dead = false;
    apiGet("/api/contests")
      .then((data) => {
        if (dead) return;
        if (data.error) setErr(data.error); else setD(data);
      });
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

  /* ---- the entries half (opt-in) ---------------------------------------------
     /api/contest/mine is telemetry-derived and instant; the sync POST is the
     fire-and-forget refresh that catches entries made on pixai.art or on another
     device. It is kicked ONCE per mount, and the re-pull happens when it answers. */
  const [mine, setMine] = useState(null);
  const [mineErr, setMineErr] = useState(null);
  const [syncing, setSyncing] = useState(wantMine);
  // The sync POST carries the explicit CSRF token like every sibling POST on this
  // surface. It rides along on /api/myart/items -- the same source PublishOverlay and
  // ContestConfirm read it from -- so this is one small GET, once, not a token minted
  // per call. Held in a ref so the effect below does not re-run when it lands.
  const csrfRef = useRef("");
  useEffect(() => {
    if (!wantMine) return;
    apiGet("/api/myart/items").then((d) => { csrfRef.current = (d && d.csrf) || ""; });
  }, [wantMine]);

  // `dead` is a REF, not a closure variable: reloadMine is called from the effect, from
  // the poll, and by consumers after an entry lands, and every one of those can resolve
  // after unmount. It used to setState unconditionally -- a stale answer could repaint a
  // gone overlay, and an in-flight read outlived the surface that asked for it.
  const deadRef = useRef(false);
  useEffect(() => {
    deadRef.current = false;
    return () => { deadRef.current = true; };
  }, []);

  const reloadMine = useCallback(() => {
    if (!wantMine) return Promise.resolve(null);
    return apiGet("/api/contest/mine").then((data) => {
      if (deadRef.current) return data;
      if (data.error) setMineErr(data.error);
      else { setMine(data); setMineErr(null); }
      return data;
    });
  }, [wantMine]);

  useEffect(() => {
    if (!wantMine) return undefined;
    let stop = false;
    let timer = null;
    reloadMine();
    // The sweep runs SERVER-SIDE ON ITS OWN THREAD now and this POST returns at once, so
    // the answer is "did one start", not "here is the result". Three shapes:
    //   started:false + skipped:"recent"  -- nothing ran; the read above is already current
    //   started:false + busy:true         -- somebody else's sweep is mid-flight; watch it
    //   started:true                      -- ours is running; watch it
    // Watching means polling /api/contest/mine (a local telemetry read) while its
    // sync_running flag is set, and stopping the moment it clears -- or after the ceiling,
    // so a wedged sweep cannot leave a tab polling forever.
    const POLL_MS = 5000;
    const CEILING_MS = 60000;
    const started = Date.now();
    const watch = () => {
      if (stop || deadRef.current) return;
      if (Date.now() - started > CEILING_MS) { setSyncing(false); return; }
      timer = setTimeout(() => {
        reloadMine().then((d) => {
          if (stop || deadRef.current) return;
          if (d && d.sync_running) { watch(); return; }
          setSyncing(false);          // it finished; the rows above are the fresh ones
        });
      }, POLL_MS);
    };
    apiPost("/api/contest/sync", { csrf: csrfRef.current }).then((d) => {
      if (stop || deadRef.current) return;
      // A refusal (an expired token, a 409, anything with an error) is NOT a completed
      // sync -- it used to fall through the same path as success and quietly report the
      // sweep as done. Surface it and stop watching.
      if (!d || d.error) {
        setSyncing(false);
        if (d && d.error) setMineErr(d.error);
        return;
      }
      if (d.skipped === "recent") { setSyncing(false); return; }
      watch();
    });
    return () => { stop = true; if (timer) clearTimeout(timer); };
  }, [wantMine, reloadMine]);

  const mineRows = mine ? mine.contests || [] : [];
  const mineBy = useMemo(() => {
    const by = {};
    for (const r of mineRows) by[String(r.contest_id)] = r;
    return by;
  }, [mine]);                                   // eslint-disable-line react-hooks/exhaustive-deps
  const entriesFor = (row) => mineBy[String((row && row.id) || "")] || null;
  const enteredCount = (row) => {
    const m = entriesFor(row);
    return m && m.entry_artwork_ids ? m.entry_artwork_ids.length : 0;
  };
  const totalEntries = mine ? mine.total_entries || 0 : 0;

  return { d, err, contests, official, community, featured, restOfficial, openContest,
           dateRange, daysLeft,
           mine, mineErr, mineRows, mineBy, entriesFor, enteredCount, totalEntries,
           syncing, reloadMine };
}

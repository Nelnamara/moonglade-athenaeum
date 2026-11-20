/* notify/trackerRows.js -- which /api/jobs rows the Activity tracker LISTS.

   Owner, 2026-11-18: "Some of these items run too god damned often. and I am sick of it
   being a ten mile list in the tracker. I want maint. jobs removed from the tracker."

   So the tracker lists what the owner set going and is waiting on -- generations, imports,
   deletes, claims, the update, a Health fix run, and a Sync (or other art-pulling Panel
   action) he pressed himself. It no longer lists:
     * anything the library ran by itself (`scheduled`: the living-library tick, the
       published-artwork sweep's boot, timer and publish kicks), whatever its type;
     * Control Panel maintenance actions (type "panel" that pull no art in: Duplicate audit,
       Catalog stats, the Similar index, hashes, organize ...), even when pressed.
   Every one of those rows is still in jobs.jsonl and still drawn by the Control Panel's
   Ledger, which is where maintenance lives. Only the LIST changes: notify/jobsStore.js still
   reads every row for its transition rules, so a pressed maintenance job still says how it
   ended in the corner, and a scheduled one still says nothing.

   Pure (no store, no DOM) so the loom node tests can import it. */
import { PANEL_ADDS_ART } from "./doneNotice.js";

export function inTracker(j) {
  if (!j || typeof j !== "object") return false;
  if (j.scheduled) return false;
  if (j.type === "panel") return PANEL_ADDS_ART.has(j.action);
  return true;
}

export function trackerRows(rows) {
  return (rows || []).filter(inTracker);
}

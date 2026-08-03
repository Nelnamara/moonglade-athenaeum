import { useEffect, useState } from "react";

/* useContactSheet -- ContactSheetOverlay.jsx's fetch/state logic, mechanically
   lifted out (2026-08-03), same precedent as useFolio.js/useHealth.js/
   useImageDetails.js/useControlPanel.js this session (see useFolio.js's own
   header comment for the full "ONE place this state has ever lived,
   refactored to CONSUME rather than duplicate" rationale). ContactSheetOverlay
   (desktop) is refactored to CONSUME this hook; the new mobile screen
   (ContactSheetMobile.jsx) gets the IDENTICAL data -- one fetch of
   GET /api/contact-sheet (moonglade_gallery.py, the real, already-shipped
   JSON twin of the classic /contact-sheet print page -- reuses
   rows_for_media_ids/query_catalog/rating->stars, no new endpoint, no second
   copy of that selection logic), never a second, drifting fetch of it.

   A byte-for-byte lift of ContactSheetOverlay.jsx's own state/effect, not a
   rewrite -- same ids-or-collection contract the route already takes:
   explicit `ids` (the Actions menu's frozen selection) wins over
   `collectionName` (the Advanced flyout's "current collection view" -- or
   the desktop-only "printCollection" entry, not yet wired anywhere on
   mobile); neither reads live filter state after the sheet opens, so what's
   shown matches what was selected/viewed at open time, on both surfaces.

   `shareUrl` is new (desktop's own component never needed it -- window.print()
   just prints the live DOM): the SAME ids-or-collection querystring, aimed at
   the classic `/contact-sheet` print page instead of the JSON route, for
   ContactSheetMobile.jsx's Share action to hand to the OS-native share sheet
   (see that file's header comment for why a real page URL, not window.print(),
   is the right target on mobile). Computed once here, off the identical
   `ids`/`collectionName` inputs the fetch itself uses, so the two can never
   drift apart into "shared a different set than it fetched." */

// Shared frame-number formatter ("No. 001") -- ContactSheetOverlay.jsx's own
// prior local helper, moved here so both consumers number frames identically
// (matches useFolio.js's fmt/useHealth.js's fmt precedent for a small shared
// pure formatter living alongside its data hook).
export function pad(n, width) { return String(n).padStart(width, "0"); }

export default function useContactSheet({ ids, collectionName }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  const qs = ids && ids.length
    ? "ids=" + encodeURIComponent(ids.join(","))
    : collectionName
      ? "collection=" + encodeURIComponent(collectionName)
      : "";

  useEffect(() => {
    let dead = false;
    fetch("/api/contact-sheet" + (qs ? "?" + qs : ""))
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((d) => { if (!dead) setData(d); })
      .catch((e) => { if (!dead) setErr(String(e.message || e)); });
    return () => { dead = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids, collectionName]);

  return { data, err, shareUrl: "/contact-sheet" + (qs ? "?" + qs : "") };
}

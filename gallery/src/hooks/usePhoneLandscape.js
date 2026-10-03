import { useEffect, useState } from "react";
import { LANDSCAPE_QUERY, TURN_SETTLE_MS, phoneColumns } from "../lib/phoneCore.js";

/* Is the phone held sideways, and how many columns does its gallery draw? (Session Q, Q4.)

   Live, like hooks/useIsMobile.js: it follows the media query, resize and orientationchange, so a
   turn re-flows the columns on the spot. The query is lib/phoneCore.js's LANDSCAPE_QUERY -- the same
   condition phone-landscape.css is written under, so the columns and the CSS rail cannot disagree.
   It reads only; nothing here writes anywhere.

   AND AGAIN ONCE THE TURN HAS SETTLED (owner's walk, 2026-10-03): a phone can deliver a turn's events
   while the query still answers for the old way up, and fire nothing afterwards, which left the
   sideways column count on an upright phone. Every event also reads on the next frame and at
   TURN_SETTLE_MS; the visual viewport's resize (what a phone fires when its toolbars settle) counts. */

function read() {
  if (typeof window === "undefined" || !window.matchMedia) return { landscape: false, cols: 2 };
  const landscape = window.matchMedia(LANDSCAPE_QUERY).matches;
  return { landscape, cols: phoneColumns(window.innerWidth, landscape) };
}

export default function usePhoneLandscape() {
  const [st, setSt] = useState(read);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return undefined;
    const sync = () => setSt((old) => {
      const next = read();
      return old.landscape === next.landscape && old.cols === next.cols ? old : next;
    });
    let raf = 0;
    let timers = [];
    const settle = () => {
      sync();
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => { raf = 0; sync(); });
      timers.forEach(clearTimeout);
      timers = TURN_SETTLE_MS.map((ms) => setTimeout(sync, ms));
    };
    sync();
    const mql = window.matchMedia(LANDSCAPE_QUERY);
    const vv = window.visualViewport;
    if (mql.addEventListener) mql.addEventListener("change", settle); else if (mql.addListener) mql.addListener(settle);
    window.addEventListener("resize", settle);
    window.addEventListener("orientationchange", settle);
    if (vv) vv.addEventListener("resize", settle);
    return () => {
      if (mql.removeEventListener) mql.removeEventListener("change", settle); else if (mql.removeListener) mql.removeListener(settle);
      window.removeEventListener("resize", settle);
      window.removeEventListener("orientationchange", settle);
      if (vv) vv.removeEventListener("resize", settle);
      if (raf) cancelAnimationFrame(raf);
      timers.forEach(clearTimeout);
    };
  }, []);
  return st;
}

import { useEffect, useState } from "react";
import { LANDSCAPE_QUERY, phoneColumns } from "../lib/phoneCore.js";

/* Is the phone held sideways, and how many columns does its gallery draw? (Session Q, Q4.)

   Live, like hooks/useIsMobile.js: it follows the media query, resize and orientationchange, so a
   turn re-flows the columns on the spot. The query is lib/phoneCore.js's LANDSCAPE_QUERY -- the same
   condition phone-landscape.css is written under, so the columns and the CSS rail cannot disagree.
   It reads only; nothing here writes anywhere. */

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
    sync();
    const mql = window.matchMedia(LANDSCAPE_QUERY);
    if (mql.addEventListener) mql.addEventListener("change", sync); else mql.addListener(sync);
    window.addEventListener("resize", sync);
    window.addEventListener("orientationchange", sync);
    return () => {
      if (mql.removeEventListener) mql.removeEventListener("change", sync); else mql.removeListener(sync);
      window.removeEventListener("resize", sync);
      window.removeEventListener("orientationchange", sync);
    };
  }, []);
  return st;
}

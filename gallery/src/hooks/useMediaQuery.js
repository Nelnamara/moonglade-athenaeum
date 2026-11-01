import { useEffect, useState } from "react";

/* One CSS media query, live: true while it matches. For markup that has to MOVE at a breakpoint
   (CSS can restyle a node but cannot re-parent it), so the JS line and the stylesheet's line are
   the same query text and flip together. useIsMobile.js is the phone decision built on the same
   matchMedia subscription; this is the plain one-query form of it. Read synchronously on first
   render, so the first paint is already on the right side of the line. */
function read(query) {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia(query).matches;
}

export default function useMediaQuery(query) {
  const [matches, setMatches] = useState(() => read(query));

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return undefined;
    const mql = window.matchMedia(query);
    const sync = () => setMatches(mql.matches);
    sync();   // the viewport may have settled between the first render and this commit
    // addEventListener is modern; addListener is the Safari < 14 fallback (as useIsMobile.js).
    if (mql.addEventListener) mql.addEventListener("change", sync); else mql.addListener(sync);
    return () => {
      if (mql.removeEventListener) mql.removeEventListener("change", sync); else mql.removeListener(sync);
    };
  }, [query]);

  return matches;
}

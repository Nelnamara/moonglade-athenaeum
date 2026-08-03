import { useEffect, useState } from "react";

/* Reactive mobile-viewport detection -- the first hook in gallery/src/hooks/
   built for a viewport-driven surface (LoginPageMobile.jsx, 2026-08-02) and
   meant to be the shared pattern every future mobile surface reuses, so it
   follows useFlavour.js's own convention exactly: default export, `use`-
   prefixed name matching the filename, imported with an explicit `.js`
   extension.

   A REAL reactive hook, not a one-shot width check at mount -- it subscribes
   to a matchMedia query and re-renders on resize/orientation change (rotating
   a phone, or a desktop window dragged narrow, must flip the presentation
   live, not just on first paint).

   Breakpoint: 430px. Login Mobile.dc.html proves the design out at 390px
   (an iPhone frame's CSS width); 430px adds headroom so the widest current
   phones (iPhone Pro Max class, ~428-430px CSS width) still get the mobile
   build, without pulling in a small tablet held in portrait. */
const MOBILE_QUERY = "(max-width: 430px)";

export default function useIsMobile() {
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== "undefined" && window.matchMedia
      ? window.matchMedia(MOBILE_QUERY).matches
      : false
  );

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mql = window.matchMedia(MOBILE_QUERY);
    // Re-sync in case the viewport changed between the lazy initializer above
    // (which runs at module/first-render time) and this effect committing.
    setIsMobile(mql.matches);
    const onChange = (e) => setIsMobile(e.matches);
    // addEventListener is the modern API; addListener is the Safari <14 /
    // older embedded-WebView fallback -- still real out there, cheap to keep.
    if (mql.addEventListener) mql.addEventListener("change", onChange);
    else mql.addListener(onChange);
    return () => {
      if (mql.removeEventListener) mql.removeEventListener("change", onChange);
      else mql.removeListener(onChange);
    };
  }, []);

  return isMobile;
}

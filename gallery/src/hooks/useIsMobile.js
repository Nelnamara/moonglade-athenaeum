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

/* One decision, evaluated live. The primary signal is the layout-viewport width
   (the max-width query). The FALLBACK exists because iOS Chrome (CriOS) and
   Firefox (FxiOS) -- same WebKit as Safari, but different UA shells -- were
   showing the DESKTOP build on phones where Safari correctly showed mobile
   (owner-reported 2026-08-08): on those shells the layout viewport can report
   desktop-wide on the first load(s), so the pure max-width query misses a real
   phone. A COARSE-pointer device held in PORTRAIT whose PHYSICAL screen is
   phone-width (screen.width, which is independent of the layout-viewport quirk)
   is a phone regardless of what innerWidth claims. Both extra clauses are
   necessary to stay off desktops: a mouse laptop is never coarse-pointer, and a
   real tablet's screen.width is > 430 -- so neither can trip this. Landscape is
   deliberately left to the desktop build, exactly as the max-width query did. */
function detectMobile() {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  if (window.matchMedia(MOBILE_QUERY).matches) return true;
  const coarse = window.matchMedia("(pointer: coarse)").matches;
  const portrait = window.matchMedia("(orientation: portrait)").matches;
  const screenW = (window.screen && window.screen.width) || Infinity;
  return coarse && portrait && screenW <= 430;
}

export default function useIsMobile() {
  const [isMobile, setIsMobile] = useState(detectMobile);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    // Recompute the whole decision on any change -- the fallback depends on
    // orientation and screen metrics, not just the max-width breakpoint.
    const sync = () => setIsMobile(detectMobile());
    sync();   // re-sync after commit (viewport may have settled since first render)
    const mqls = [
      window.matchMedia(MOBILE_QUERY),
      window.matchMedia("(orientation: portrait)"),
    ];
    // addEventListener is modern; addListener is the Safari <14 / older-WebView
    // fallback -- still real out there, cheap to keep.
    const bind = (mql) => (mql.addEventListener
      ? mql.addEventListener("change", sync) : mql.addListener(sync));
    const unbind = (mql) => (mql.removeEventListener
      ? mql.removeEventListener("change", sync) : mql.removeListener(sync));
    mqls.forEach(bind);
    window.addEventListener("resize", sync);
    window.addEventListener("orientationchange", sync);
    return () => {
      mqls.forEach(unbind);
      window.removeEventListener("resize", sync);
      window.removeEventListener("orientationchange", sync);
    };
  }, []);

  return isMobile;
}

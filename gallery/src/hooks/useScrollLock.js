import { useEffect } from "react";

/* useScrollLock -- body scroll stops while any full-screen panel is open (owner
   report 2026-08-06: "Can the gallery not scroll when panels are open? Health,
   folio, control panel etc. its a bit of an annoyance").

   Reference-counted: overlays stack (Control Panel -> its Trash sub-overlay;
   Lightbox -> Details), so a plain save/restore pair would un-lock the page the
   moment the INNER layer closed while the outer one was still up. The body
   locks when the first layer mounts and restores the original overflow only
   when the LAST one unmounts. Same body-overflow mechanism LoomMobile's own
   full-screen effect already uses -- this is that pattern, shared.

   THE WIDTH JUMP (perf, 2026-09-04). Hiding the body's overflow removes the scrollbar on a
   classic-scrollbar platform, which WIDENS the viewport by ~15px on the exact frame an
   overlay is animating in: the page shifts sideways under the scrim, and every
   ResizeObserver in the shell (App.jsx's two, Grid.jsx's column measure) fires mid-open.
   styles.css reserves the track permanently with `scrollbar-gutter: stable`, which makes
   this a non-event -- the fallback below is only for engines that do not support that
   property (older Safari).

   MEASURED, not assumed (Chromium, 1280px viewport, 2026-09-04), watching the clientWidth
   of an element inside <body> across the lock:
     gutter reserved + lock                    ->   0  (what ships)
     no gutter       + lock                    -> +15  (the bug: the page really does widen)
     no gutter       + lock + padding          ->   0  (the fallback works)
     gutter reserved + lock + padding          -> -15  (over-corrected, the other way)
   That last row is why the feature detection below is REQUIRED rather than tidy: applying
   both fixes is as wrong as applying neither. Overlay scrollbars (macOS default, phones)
   have no width, so the measured compensation is 0 there and nothing is padded either way. */
let _locks = 0;
let _prevOverflow = "";
let _prevPadRight = "";

function _gutterIsReserved() {
  try {
    return typeof CSS !== "undefined" && CSS.supports
      && CSS.supports("scrollbar-gutter", "stable");
  } catch { return false; }
}

export default function useScrollLock() {
  useEffect(() => {
    if (_locks === 0) {
      _prevOverflow = document.body.style.overflow;
      if (!_gutterIsReserved()) {
        const bar = window.innerWidth - document.documentElement.clientWidth;
        if (bar > 0) {
          _prevPadRight = document.body.style.paddingRight;
          document.body.style.paddingRight = bar + "px";
        }
      }
      document.body.style.overflow = "hidden";
    }
    _locks += 1;
    return () => {
      _locks -= 1;
      if (_locks === 0) {
        document.body.style.overflow = _prevOverflow;
        if (!_gutterIsReserved()) { document.body.style.paddingRight = _prevPadRight; }
      }
    };
  }, []);
}

import React, { useEffect, useRef } from "react";

/* Generic full-screen PUSH chrome -- the SECOND shared chrome primitive after
   MobileSheet.jsx (bottom sheet). Built for surfaces that replace the current
   tab's own content entirely (design spec: Moonglade Mobile.dc.html's
   Advanced screen, lines 333-339 & 1109-1120: back chevron + title header,
   scrollable body, no footer) rather than sliding up over it like a sheet
   does. No prior full-screen-push convention existed anywhere in this
   codebase's mobile surfaces (gallery-mobile.css/login-mobile.css/setup-
   wizard-mobile.css only ever define sheet/placeholder/modal chrome) --
   CreateMobile.jsx's Advanced screen is the first thing that needed one, so
   this is a new dedicated pattern, not a raw copy of MobileSheet.jsx's
   bottom-sheet chrome (different geometry, different dismissal contract) and
   not a third ad-hoc convention invented inline in CreateMobile.jsx either.

   Same OWNERSHIP CONTRACT as MobileSheet.jsx, deliberately mirrored so a
   second hand-rolled push-screen never has to exist: the caller owns the
   open/closing state machine (a plain boolean pair), `open` mounts it,
   `closing` swaps the entrance animation (glmScreenIn) for the exit one
   (glmScreenOut), and the caller runs the setTimeout that unmounts after the
   exit animation's 220ms (matching glmScreenIn/Out's own .22s duration, the
   same "animation duration in the CSS, timeout in the caller" discipline
   MobileSheet.jsx's 280ms uses for its own .28s animations).

   Dismissal is the design's own: tapping the back chevron is the ONLY wired
   affordance (design_handoff's own note: no swipe-back, no X button, no tap-
   outside-to-close, no Escape handling in that mock) -- so unlike
   MobileSheet.jsx there is no scrim and no onClick-outside-to-close; `onClose`
   fires from the chevron alone.

   THE SCROLLER UNDERNEATH IS PARKED WHILE A SCREEN IS UP (2026-09-05). `.glm-screen` is
   position:absolute inside `.glm-body`, and `.glm-body` is the TAB's scroller -- it still
   holds the whole tab below the screen, so its scroll offset positions this screen too.
   Two live consequences, both measured at 390x844 with the Control tab open: a screen
   opened while that tab was scrolled to 996 rendered at top -824, entirely above the
   viewport (the tap looked like it did nothing); and a flick that ran past the end of
   this screen's own body chained out into that scroller and slid the whole screen off,
   revealing the Control tab under it. gallery-mobile.css locks the scroller (`overflow:
   hidden` while a screen is mounted, which does NOT by itself move an offset already
   there), and this effect zeroes the offset on the way in and restores it on the way out,
   so the tab keeps its place when the screen closes. */
export default function MobileScreen({ open, closing, onClose, title, children }) {
  const root = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const host = root.current && root.current.closest(".glm-body");
    if (!host) return undefined;
    const was = host.scrollTop;
    host.scrollTop = 0;
    return () => { host.scrollTop = was; };
  }, [open]);
  if (!open) return null;
  return (
    <div ref={root} className={"glm-screen" + (closing ? " closing" : "")} role="dialog"
      aria-modal="true" aria-label={title || "Screen"}>
      <div className="glm-screen-head">
        <button type="button" className="glm-screen-back" onClick={onClose}
          aria-label="Back" title="Back">&lsaquo;</button>
        <div className="glm-screen-title">{title}</div>
      </div>
      <div className="glm-screen-body">{children}</div>
    </div>
  );
}

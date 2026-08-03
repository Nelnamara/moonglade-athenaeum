import React from "react";

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
   fires from the chevron alone. */
export default function MobileScreen({ open, closing, onClose, title, children }) {
  if (!open) return null;
  return (
    <div className={"glm-screen" + (closing ? " closing" : "")} role="dialog" aria-modal="true"
      aria-label={title || "Screen"}>
      <div className="glm-screen-head">
        <button type="button" className="glm-screen-back" onClick={onClose}
          aria-label="Back" title="Back">&lsaquo;</button>
        <div className="glm-screen-title">{title}</div>
      </div>
      <div className="glm-screen-body">{children}</div>
    </div>
  );
}

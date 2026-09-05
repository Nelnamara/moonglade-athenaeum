import React from "react";

/* Generic bottom-sheet chrome shared by every Gallery/Create/Control Mobile
   sheet (Advanced Search, Sort, Actions, The Loom, Menu) -- one scrim/slab
   pair, one set of timings (DC's mmSheetUp/mmSheetDown .28s, mmFade/mmFadeOut
   .24s/.28s -- ported as glmSheetUp/glmSheetDown/glmFade/glmFadeOut in
   gallery-mobile.css), so five hand-rolled copies can never drift apart.

   The caller owns the open/closing state machine (a plain boolean pair is
   enough -- see GalleryMobile.jsx's useSheet() and AppMobile.jsx's own copy):
   `open` mounts it, `closing` swaps the enter animation for the exit one, and
   the caller is responsible for the setTimeout that actually unmounts after
   the exit animation's 280ms.

   `className` is a per-CALLER hook, applied to the scrim AND the slab together,
   and it exists for exactly one job: re-rung a single sheet's z-index without
   moving the shared one. Nearly every caller mounts this INSIDE its own
   full-screen root (.idm-root, .fm-root, .mgdrm-*), whose stacking context
   already carries the pair over everything behind it, so 30/31 is right for
   them. AppMobile's sheets are the exception -- they mount at the app root, as
   SIBLINGS of those full-screen viewers -- and one of them (the contest chooser)
   opens FROM a viewer, so it alone has to clear it. Raising `.glm-sheet` itself
   would move all eleven; a class the one sheet asks for moves one. The scrim
   travels with the slab or it stops dimming and stops catching the tap-outside
   -- see contest-mobile.css's `.cmb-choosersheet` rung, and the scrim/host
   pairing discipline tests/test_z_ladder.py already enforces on the desktop
   band for the same reason. */
export default function MobileSheet({ open, closing, onClose, title, className, children }) {
  if (!open) return null;
  const extra = (className ? " " + className : "") + (closing ? " closing" : "");
  return (
    <>
      <div className={"glm-scrim" + extra} onClick={onClose} aria-hidden="true" />
      <div className={"glm-sheet" + extra} role="dialog" aria-modal="true"
        aria-label={title || "Sheet"}>
        {title ? <div className="glm-sheet-title">{title}</div> : null}
        {children}
      </div>
    </>
  );
}

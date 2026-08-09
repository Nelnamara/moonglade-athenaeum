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
   the exit animation's 280ms. */
export default function MobileSheet({ open, closing, onClose, title, children }) {
  if (!open) return null;
  return (
    <>
      <div className={"glm-scrim" + (closing ? " closing" : "")} onClick={onClose} aria-hidden="true" />
      <div className={"glm-sheet" + (closing ? " closing" : "")} role="dialog" aria-modal="true"
        aria-label={title || "Sheet"}>
        {title ? <div className="glm-sheet-title">{title}</div> : null}
        {children}
      </div>
    </>
  );
}

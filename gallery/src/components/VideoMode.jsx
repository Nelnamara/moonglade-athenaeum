import React, { useEffect, useRef } from "react";

/* Create tab, Video mode -- the shared <mg-generate-drawer> web component
   (static/mg-generate-drawer.js), the SAME element desktop's GenerateDrawer.jsx
   mounts for its own Video tab (see that file's VideoTab). No reimplementation:
   form state, live cost, submit/poll, and the result strip are all the
   component's own unchanged machinery.

   LIFTED OUT of CreateMobile.jsx (2026-08-03, credit-safety fix) to
   AppMobile.jsx itself, alongside the cmode/setCmode state -- see
   AppMobile.jsx's own header comment for the full "why lifted" list
   (useLibrary/useGenerate/cmode all follow the identical pattern: state and
   mounts that must survive a Gallery/Create/Control tab switch live in
   AppMobile, not in the tab component that gets conditionally unmounted).

   Mounting this ONE level higher than CreateMobile.jsx is not cosmetic: this
   file's own contract (imperative DOM handle, mount-once effect, registry-
   checked fallback text -- mirroring GenerateDrawer.jsx's own VideoTab mount
   exactly) exists for the one reason stated there outright: the shared
   element's disconnectedCallback sweeps EVERY outstanding poll timer
   (static/mg-generate-drawer.js lines 523-532), so unmounting it mid-submit
   would silently stop tracking an already-charged video task while the
   server-side job keeps running and billing. CreateMobile.jsx itself already
   never unmounted this element on an Image/Edit/Video segmented-control
   switch (only `visible` toggles display:none there) -- but CreateMobile.jsx
   is ALSO only rendered while AppMobile's OUTER tab === "create"
   ({tab === "create" && <CreateMobile .../>} in AppMobile.jsx), so switching
   the bottom nav to Gallery or Control unmounted CreateMobile and, with it,
   this element -- the exact silent-tracking-loss bug the inner guard was
   written to prevent, just one level up. Rendering VideoMode directly in
   AppMobile.jsx, as a sibling OUTSIDE the `tab === "create"` conditional,
   closes that gap: this component (and the custom element it mounts) is now
   never removed from the DOM by either the inner mode switch or the outer
   tab switch -- only `visible` ever toggles display:none, exactly as before,
   just one level higher up.

   Visual placement: AppMobile.jsx positions this inside an absolutely
   positioned overlay (.cm-videowrap, create-mobile.css) sized to
   .glm-body's own already-correct content area, with an invisible ghost
   copy of the segmented control reserving the same vertical gap the REAL
   one (rendered by CreateMobile.jsx, still visible and clickable underneath)
   occupies -- see create-mobile.css's .cm-videowrap block for why that
   needs no new/guessed pixel constants. */
export default function VideoMode({ visible }) {
  const host = useRef(null);
  useEffect(() => {
    if (!host.current || host.current.firstChild) return;
    if (!window.customElements || !window.customElements.get("mg-generate-drawer")) {
      host.current.textContent = "The shared video drawer script did not load.";
      return;
    }
    host.current.appendChild(document.createElement("mg-generate-drawer"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return <div ref={host} className="cm-videohost" style={{ display: visible ? "" : "none" }} />;
}

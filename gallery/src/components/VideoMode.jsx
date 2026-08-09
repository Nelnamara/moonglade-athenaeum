import React, { useRef } from "react";
import VideoDrawer from "./VideoDrawer.jsx";

/* Create tab, Video mode -- the shared video Generate form. Since the no-vanilla port
   (2026-08-08) this renders the React <VideoDrawer> (gallery/src/components/VideoDrawer.jsx),
   the SAME component desktop's GenerateDrawer.jsx mounts for its own Video tab. No
   reimplementation: form state, live cost, submit/poll, and the result strip are all
   VideoDrawer's own machinery, identical on both surfaces.

   LIFTED OUT of CreateMobile.jsx (2026-08-03, credit-safety fix) to AppMobile.jsx itself,
   alongside the cmode/setCmode state -- see AppMobile.jsx's own header comment for the full
   "why lifted" list.

   Mounting this ONE level higher than CreateMobile.jsx is not cosmetic, and the reason SURVIVES
   the vanilla->React port: VideoDrawer's unmount effect sweeps EVERY outstanding poll timer (its
   pollTimers ref, mirroring the old custom element's disconnectedCallback), so unmounting it
   mid-submit would silently stop tracking an already-charged video task while the server-side job
   keeps running and billing. CreateMobile.jsx itself already never unmounted on an Image/Edit/
   Video segmented-control switch (only `visible` toggles display:none) -- but CreateMobile.jsx is
   ALSO only rendered while AppMobile's OUTER tab === "create", so switching the bottom nav to
   Gallery or Control unmounted CreateMobile and, with it, this form -- the exact silent-tracking-
   loss bug. Rendering VideoMode directly in AppMobile.jsx, as a sibling OUTSIDE the
   `tab === "create"` conditional, closes that gap: this component (and VideoDrawer) is now never
   removed from the DOM by either the inner mode switch or the outer tab switch -- only `visible`
   ever toggles display:none.

   Visual placement: AppMobile.jsx positions this inside an absolutely positioned overlay
   (.cm-videowrap, create-mobile.css) sized to .glm-body's own already-correct content area, with
   an invisible ghost copy of the segmented control reserving the same vertical gap the REAL one
   (rendered by CreateMobile.jsx, still visible and clickable underneath) occupies. */
export default function VideoMode({ visible }) {
  const drawerRef = useRef(null);
  return (
    <div className="cm-videohost" style={{ display: visible ? "" : "none" }}>
      <VideoDrawer ref={drawerRef} />
    </div>
  );
}

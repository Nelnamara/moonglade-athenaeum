import React, { useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import ClipMoment from "./ClipMoment.jsx";
import { currentMoment, subscribe } from "./momentStore.js";

/* Puts the requested moment on screen. Rendered by <NotifyRoot/>, so every shell that renders
   that root -- the desktop gallery, the phone, the Loom -- can play one; notify/index.jsx is
   where the store is registered as ach.js's moment host. Portaled to document.body like the
   rest of the celebration layer, keyed by the request so a new moment is a fresh mount. */
export default function MomentHost() {
  const cur = useSyncExternalStore(subscribe, currentMoment, currentMoment);
  if (!cur || typeof document === "undefined") return null;
  return createPortal(<ClipMoment key={cur.id} moment={cur} />, document.body);
}

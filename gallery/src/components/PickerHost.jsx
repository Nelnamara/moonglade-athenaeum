import React, { useEffect, useState } from "react";
import GalleryPicker from "./GalleryPicker.jsx";

/* One gallery-image picker for the whole app, riding the shared <GalleryPicker> React
   component (2026-08-08: was the <mg-gallery-picker> web component, mount-to-open /
   unmount-to-close; the component is now a real React child instead of an imperatively
   appended custom element). ask(opts) returns a promise resolving to the picked
   {media_id, thumb, is_video, is_nsfw, prompt} or null on close. Also answers the video
   drawer's mg-pick-request document events (the classic host contract). */

let _ask = null;
let _open = false;
export function askPicker(opts) {
  return _ask ? _ask(opts) : Promise.resolve(null);
}
// The drawer's Escape handler asks this so dismissing the picker doesn't also
// close the drawer underneath it.
export function isPickerOpen() { return _open; }

export default function PickerHost() {
  const [open, setOpen] = useState(null); // {type, resolve}

  useEffect(() => {
    _ask = (opts = {}) => new Promise((resolve) => setOpen({ type: opts.type || "image", resolve }));
    // The shared video drawer asks its host for reference images this way.
    const onPickReq = (e) => {
      const d = e.detail || {};
      _ask({ type: d.kind === "video" ? "video" : "image" }).then((m) => {
        // respond(media_id, thumb, is_nsfw) -- the third arg carries the blur
        // flag onto the drawer's slot; dropping it un-blurs NSFW references.
        if (m && d.respond) d.respond(m.media_id, m.thumb, m.is_nsfw);
      });
    };
    document.addEventListener("mg-pick-request", onPickReq);
    return () => { _ask = null; document.removeEventListener("mg-pick-request", onPickReq); };
  }, []);

  useEffect(() => { _open = !!open; }, [open]);

  if (!open) return null;
  // GalleryPicker IS the scrim (fixed inset-0, its own backdrop/Escape). One resolve path:
  // onPick with the media, onClose with null -- both close the singleton.
  const done = (m) => { const r = open.resolve; setOpen(null); r(m); };
  return (
    <GalleryPicker defaultType={open.type} showType showUpload={open.type === "image"}
      onPick={done} onClose={() => done(null)} />
  );
}

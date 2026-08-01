import React, { useEffect, useRef, useState } from "react";

/* One gallery-image picker for the whole pilot, riding the shared
   <mg-gallery-picker> web component (mount-to-open / unmount-to-close).
   ask(opts) returns a promise resolving to the picked {media_id, thumb,
   is_video, is_nsfw, prompt} or null on close. Also answers the video
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
  const hostRef = useRef(null);

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

  useEffect(() => {
    if (!open || !hostRef.current) return;
    const el = document.createElement("mg-gallery-picker");
    el.setAttribute("default-type", open.type);
    el.setAttribute("show-type", "");
    const done = (m) => { const r = open.resolve; setOpen(null); r(m); };
    el.addEventListener("mg-pick", (e) => done(e.detail));
    el.addEventListener("mg-close", () => done(null));
    hostRef.current.appendChild(el);
    return () => { el.remove(); };
  }, [open]);

  if (!open) return null;
  return (
    <div className="lb" onClick={() => { const r = open.resolve; setOpen(null); r(null); }}>
      <div className="pickwrap" onClick={(e) => e.stopPropagation()} ref={hostRef} />
    </div>
  );
}

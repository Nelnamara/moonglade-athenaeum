import { useEffect } from "react";

/* useScrollLock -- body scroll stops while any full-screen panel is open (owner
   report 2026-08-06: "Can the gallery not scroll when panels are open? Health,
   folio, control panel etc. its a bit of an annoyance").

   Reference-counted: overlays stack (Control Panel -> its Trash sub-overlay;
   Lightbox -> Details), so a plain save/restore pair would un-lock the page the
   moment the INNER layer closed while the outer one was still up. The body
   locks when the first layer mounts and restores the original overflow only
   when the LAST one unmounts. Same body-overflow mechanism LoomMobile's own
   full-screen effect already uses -- this is that pattern, shared. */
let _locks = 0;
let _prevOverflow = "";

export default function useScrollLock() {
  useEffect(() => {
    if (_locks === 0) {
      _prevOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    }
    _locks += 1;
    return () => {
      _locks -= 1;
      if (_locks === 0) document.body.style.overflow = _prevOverflow;
    };
  }, []);
}

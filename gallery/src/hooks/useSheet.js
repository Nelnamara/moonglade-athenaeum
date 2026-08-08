import { useEffect, useRef, useState } from "react";

/* The one correct MobileSheet open/close state machine, promoted verbatim from
   GalleryMobile.jsx's private useSheet (2026-08-07 branch review): every OTHER
   caller of MobileSheet hand-rolled the {sheet, closing, 280ms unmount timer}
   trio and got the same race wrong -- reopening a sheet inside the previous
   sheet's 280ms exit window left `closing` stale and let the stale timer fire
   setSheet(null), so the NEW sheet mounted mid-exit-animation and then vanished.
   The cure is what GalleryMobile always did: clearTimeout on BOTH open and
   close, reset `closing` on open, and clear the timer on unmount.

   `ms` exists because MobileScreen's exit animation runs 220ms, not the sheets'
   280ms -- pass the number that matches the CSS the caller renders with. */
export default function useSheet(ms = 280) {
  const [sheet, setSheet] = useState(null);
  const [closing, setClosing] = useState(false);
  const timer = useRef(null);
  const open = (name) => { clearTimeout(timer.current); setClosing(false); setSheet(name); };
  const close = () => {
    setClosing(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { setSheet(null); setClosing(false); }, ms);
  };
  useEffect(() => () => clearTimeout(timer.current), []);
  return { sheet, closing, open, close };
}

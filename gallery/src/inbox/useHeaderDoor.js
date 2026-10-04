import { useCallback, useEffect, useRef, useState } from "react";

/* THE HEADER'S TWO DOORS (owner's walk, 2026-10-04): ✉ Inbox and 🎁 Gift box, side by side left of
   the credits chip. The gift box is for rewards only; the inbox has its own button. Each opens its
   own panel with the behaviour Session R built for the one door (Inbox and Event Handoff §1): enter
   .42 s and exit .35 s with a deferred unmount (CLOSE_MS), Esc, an outside click or the button
   closes it, and reduced motion drops the translate (inbox.css). The two panels are separate:
   opening one closes the other -- by any route, a click or the keyboard, so the rule does not ride
   on the outside-click's mousedown. `onOpen` runs the opening's reads; a door never writes. */

export const CLOSE_MS = 350;

const others = new Set();    // every mounted door's "a door opened" listener

export default function useHeaderDoor(name, onOpen) {
  const [open, setOpen] = useState(false);
  const [closing, setClosing] = useState(false);
  const wrap = useRef(null);
  const timer = useRef(0);
  const shown = useRef(false);          // open and not closing

  const close = useCallback(() => {
    if (!shown.current) return;
    shown.current = false;
    clearTimeout(timer.current);
    setClosing(true);
    timer.current = setTimeout(() => { setOpen(false); setClosing(false); }, CLOSE_MS);
  }, []);

  const toggle = () => {
    if (shown.current) { close(); return; }
    clearTimeout(timer.current);
    shown.current = true;
    setClosing(false);
    setOpen(true);
    others.forEach((fn) => fn(name));
    if (onOpen) onOpen();
  };

  useEffect(() => {
    const fn = (who) => { if (who !== name) close(); };
    others.add(fn);
    return () => { others.delete(fn); };
  }, [name, close]);
  useEffect(() => () => clearTimeout(timer.current), []);

  useEffect(() => {
    if (!open || closing) return undefined;
    const onDoc = (e) => { if (wrap.current && !wrap.current.contains(e.target)) close(); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open, closing, close]);

  return { open, closing, lifted: open && !closing, wrap, toggle, close };
}

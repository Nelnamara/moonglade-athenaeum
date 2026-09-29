import { useEffect, useLayoutEffect, useRef } from "react";
import { LANDSCAPE_QUERY, anchorScrollTop, pickAnchor } from "../lib/phoneCore.js";

/* Rotation keeps your place (Session Q, Q4). Watches the gallery's scroller and, when the phone is
   turned (the geometry key changes and the columns re-flow), scrolls the SAME picture back to the same
   spot instead of trusting a pixel offset into a list that is now a different height.

   HOW. While the phone rests, a scroll (one frame at a time) notes which picture is at the top of the
   view and how far below the top edge it sits. The moment the turn happens the browser re-lays the
   page out and may clamp the scroll offset and fire a scroll event of its own -- so scroll events that
   arrive while the orientation no longer matches the one the note was made in are ignored, and the
   note from before the turn is what the layout effect reads. `key` changes with the orientation and
   the column count; the effect runs after React has re-flowed the columns and puts the picture back.

   Reads only, then one scrollTop write after a turn. Nothing is stored.

   `hostSel` is the scroller ("`.glm-body`"), `rootRef` any element inside it, and each picture wears
   `data-mid`. */

const TILE = "[data-mid]";

function landscapeNow() {
  try { return !!(window.matchMedia && window.matchMedia(LANDSCAPE_QUERY).matches); } catch { return false; }
}

export default function useScrollAnchor(rootRef, hostSel, key) {
  const note = useRef(null);          // {id, offset} noted while at rest
  const settled = useRef(landscapeNow());
  const lastKey = useRef(key);

  const hostOf = () => (rootRef.current && rootRef.current.closest(hostSel)) || null;
  // Where the visible area starts: under the sticky search bar when there is one.
  const viewTopOf = (host) => {
    const bar = host.querySelector(".glm-bar");
    const hb = host.getBoundingClientRect();
    return bar ? Math.max(hb.top, bar.getBoundingClientRect().bottom) : hb.top;
  };

  useEffect(() => {
    const host = hostOf();
    if (!host) return undefined;
    let raf = 0;
    const measure = () => {
      raf = 0;
      if (landscapeNow() !== settled.current) return;      // a turn is in flight: keep the note from before it
      const tiles = [...host.querySelectorAll(TILE)].map((el) => {
        const r = el.getBoundingClientRect();
        return { id: el.getAttribute("data-mid"), top: r.top, bottom: r.bottom };
      });
      note.current = pickAnchor(tiles, viewTopOf(host));
    };
    const onScroll = () => { if (!raf) raf = requestAnimationFrame(measure); };
    host.addEventListener("scroll", onScroll, { passive: true });
    measure();
    return () => { host.removeEventListener("scroll", onScroll); if (raf) cancelAnimationFrame(raf); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useLayoutEffect(() => {
    if (lastKey.current === key) return;
    lastKey.current = key;
    const host = hostOf();
    const n = note.current;
    settled.current = landscapeNow();
    if (!host || !n) return;
    const el = [...host.querySelectorAll(TILE)].find((e) => e.getAttribute("data-mid") === n.id);
    if (!el) return;
    host.scrollTop = anchorScrollTop(host.scrollTop, el.getBoundingClientRect().top, viewTopOf(host), n.offset);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
}

import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import GalleryGridMobile from "./GalleryGridMobile.jsx";
import {
  WINDOW_PAGE, mountWindow, remountShift, rulePage, windowPageCount, windowPageOf,
} from "../lib/phoneCore.js";
import "../styles/phone-u.css";

/* The phone's Continuous list (Session U, U4a; Phone Paging and Nudge Handoff.dc.html section 4): every
   loaded picture stays in memory, but at most five window pages of 100 are in the DOM. Each mounted page
   is the shipped grid (GalleryGridMobile, with its own tap / long-press / select gestures and layouts);
   a page scrolled out of the window leaves a spacer of exactly the height it had, and scrolling back
   mounts it again from memory -- its tiles paint their tint, then their pictures, and since a tile's box
   is its aspect ratio nothing shifts.

   THE WINDOW follows the page at the middle of the view (checked once a frame while the list scrolls,
   and again when the list grows). A spacer's height is the page's measured height for this layout --
   keyed by the layout, the column count, the list's width and the pictures the page holds -- or, for a
   page never measured that way (after a turn of the phone, or a pull that moved the page edges), an
   estimate from the pages that were, and failing that the height it last had. Whenever a page above
   the view changes height between two frames (a page mounted again over an estimate, an estimate
   refined) the view follows it by the difference (phoneCore.remountShift), so nothing in view moves --
   the scroll anchoring a browser does on its own, done here because iPhone Safari does not.

   THE RULE ("N new since HH:MM") is drawn inside the page its last new picture is on, at its place.

   `reveal` ({mid, n}) is the shell's ask after the viewer closes: bring that picture back into view,
   mounting its page first if it was dropped. */

const MID = "[data-mid]";

export default function ContinuousGridMobile({
  items, loading, newCount = 0, newLabel = "", layout, cols, saver, reveal, ...grid
}) {
  const rootRef = useRef(null);
  const n = items.length;
  const pages = windowPageCount(n);
  const [center, setCenter] = useState(0);
  const win = mountWindow(center, pages);
  const [width, setWidth] = useState(0);
  const shape = layout + "|" + cols + "|" + width;
  const rp = rulePage(newCount);
  const countOf = (k) => Math.min(n, (k + 1) * WINDOW_PAGE) - k * WINDOW_PAGE;

  /* Heights: measured per page per shape; `rate` is px per picture for a shape (the estimate); `last`
     is each page's height in the last frame, whatever drew it. */
  const heights = useRef(new Map());
  const rate = useRef(new Map());
  const last = useRef(new Map());
  const keyOf = (k) => {
    const a = items[k * WINDOW_PAGE];
    const b = items[Math.min(n, (k + 1) * WINDOW_PAGE) - 1];
    return shape + "|" + (a ? a.media_id : "") + "|" + (b ? b.media_id : "") + "|" + (k === rp ? newCount : "");
  };
  const heightOf = (k) => {
    const h = heights.current.get(keyOf(k));
    if (h != null) return h;
    const per = rate.current.get(shape);
    if (per) return Math.round(per * countOf(k));
    return last.current.get(k) || 0;
  };

  const hostOf = () => (rootRef.current && rootRef.current.closest(".glm-body")) || null;

  /* The list's width: a change re-keys every height (a turn, a resize). */
  useLayoutEffect(() => {
    const el = rootRef.current;
    if (!el) return undefined;
    const read = () => setWidth(Math.round(el.clientWidth));
    read();
    if (typeof ResizeObserver !== "function") return undefined;
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  /* Which page is at the middle of the view. */
  const pick = useRef(() => {});
  pick.current = () => {
    const host = hostOf();
    const root = rootRef.current;
    if (!host || !root || !pages) return;
    const hb = host.getBoundingClientRect();
    const mid = hb.top + host.clientHeight / 2;
    let c = pages - 1;
    for (const el of root.children) {
      const at = el.getAttribute("data-page");
      if (at != null && el.getBoundingClientRect().bottom > mid) { c = Number(at) || 0; break; }
    }
    setCenter((old) => (old === c ? old : c));
  };
  useEffect(() => {
    const host = hostOf();
    if (!host) return undefined;
    let raf = 0;
    const onScroll = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; pick.current(); }); };
    host.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      host.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, []);
  useEffect(() => { pick.current(); }, [pages]);

  /* After each commit: measure; and when a page above the view changed height since the last frame,
     move the view by the difference. */
  useLayoutEffect(() => {
    const host = hostOf();
    const root = rootRef.current;
    if (!root) return;
    const viewTop = host ? host.getBoundingClientRect().top : 0;
    let shift = 0;          // what the pages above the view, in order, changed by
    let above = true;       // still among the pages that were wholly above the view before this frame
    let sum = 0;
    let count = 0;
    const now = new Map();
    for (const el of root.children) {
      const at = el.getAttribute("data-page");
      if (at == null) continue;
      const k = Number(at) || 0;
      const h = el.offsetHeight;
      now.set(k, h);
      if (el.classList.contains("glm-cpage")) {
        heights.current.set(keyOf(k), h);
        sum += h;
        count += countOf(k);
      }
      if (!above) continue;
      const was = last.current.get(k);
      if (was == null) { above = false; continue; }
      // where this page's foot was before the frame: its top now, less what the pages above it moved
      const bottomBefore = el.getBoundingClientRect().top - shift + was;
      const d = remountShift(was, h, bottomBefore, viewTop);
      if (bottomBefore > viewTop) above = false;
      shift += d;
    }
    if (count) rate.current.set(shape, sum / count);
    last.current = now;
    if (shift && host) host.scrollTop += shift;
  });

  /* The viewer closed on a picture: mount its page and bring it into view, before the frame paints. */
  const revealDone = useRef(null);
  useLayoutEffect(() => {
    if (!reveal || !reveal.mid || revealDone.current === reveal.n) return;
    const at = items.findIndex((it) => it.media_id === reveal.mid);
    if (at < 0) { revealDone.current = reveal.n; return; }
    const k = windowPageOf(at);
    if (k < win.start || k > win.end) { setCenter(k); return; }
    revealDone.current = reveal.n;
    const host = hostOf();
    const el = rootRef.current && [...rootRef.current.querySelectorAll(MID)].find((e) => e.getAttribute("data-mid") === reveal.mid);
    if (!host || !el) return;
    const hb = host.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    if (r.top >= hb.top && r.bottom <= hb.bottom) return;   // already in view: leave the list alone
    host.scrollTop += r.top - hb.top - Math.max(0, (host.clientHeight - r.height) / 2);
  });

  const out = [];
  for (let k = 0; k < pages; k += 1) {
    if (k < win.start || k > win.end) {
      out.push(<div key={"s" + k} className="glm-cpage-spacer" data-page={k} style={{ height: heightOf(k) + "px" }} aria-hidden="true" />);
      continue;
    }
    const slice = items.slice(k * WINDOW_PAGE, (k + 1) * WINDOW_PAGE);
    out.push(
      <div key={"p" + k} className="glm-cpage" data-page={k}>
        <GalleryGridMobile items={slice} loading={loading} layout={layout} cols={cols} saver={saver}
          newCount={k === rp ? newCount - k * WINDOW_PAGE : 0} newLabel={k === rp ? newLabel : ""} {...grid} />
      </div>
    );
  }
  return (
    <div className="glm-cpages" ref={rootRef}>
      {n ? out : <GalleryGridMobile items={items} loading={loading} layout={layout} cols={cols} saver={saver} {...grid} />}
    </div>
  );
}

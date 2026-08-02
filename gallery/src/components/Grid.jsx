import React, { useEffect, useRef, useState } from "react";
import Stars from "./Stars.jsx";
import "../styles/grid.css";

/* The grid, refit to the Frontend Gallery DC (drift §9): masonry rhythm (every
   6th card spans 2 rows), SIZE-slider cell sizing via --thumb, reveal-on-hover
   caption slab with Open/Details chips, metallic source pills, and the full
   select grammar:

     · the 15×15 checkbox ALWAYS single-toggles — no mode needed;
     · shift-click = range from the last pick, ctrl/⌘-click = toggle — both
       work with Select OFF;
     · Select ON = every card click selects, plus drag-marquee on the grid
       (rubber band, live hit-test, the post-drag click swallowed once);
     · a plain click opens the Lightbox.

   REAL pagination stays -- Prev/Next + page numbers, matching the classic
   gallery. Infinite scroll was tried here and was wrong for this surface
   (owner QA 2026-07-30: "why have a per page setting" if the grid never stops
   loading, and a 35k-deep library makes an ever-growing DOM a real problem).
   Infinite scroll stays exactly where it already lived and belongs -- the
   picker, which is the shared <mg-gallery-picker> component, not this one.

   Selection ownership: App.jsx keeps the Set (by media_id) + toggleSelected;
   the range/marquee grammar lives HERE and speaks through that same toggle
   (functional updates in App make a burst of toggles safe). lastPick is
   index-local to this page, like the DC. The marquee REPLACES the selection
   (DC semantics) — but only across THIS page's cards; picks made on other
   pages are left alone, because off-page cards can't be hit-tested. */
export default function Grid({
  items, total, loading, page, pages, goToPage,
  blur, thumb, selectMode, selected, toggleSelected, openLightbox, onRate,
  onOpenDetails,
}) {
  const go = (p) => {
    if (p < 1 || p > pages || p === page) return;
    goToPage(p);
    window.scrollTo({ top: 0, behavior: "instant" in document.documentElement.style ? "instant" : "auto" });
  };

  /* ---- select grammar (ported near-verbatim from the DC class) ---- */
  const gridRef = useRef(null);
  const lastPickRef = useRef(null);
  // Mirror of the App-owned Set, so burst operations (range, marquee commit)
  // diff against the freshest value without waiting a render.
  const selectedRef = useRef(selected);
  useEffect(() => { selectedRef.current = selected; });
  // The shift-range anchor is an INDEX into the current page's items -- carrying it
  // across a page flip would range-add against a stale anchor from the old page.
  useEffect(() => { lastPickRef.current = null; }, [items]);

  const togglePick = (i) => {
    lastPickRef.current = i;
    toggleSelected(items[i].media_id);
  };
  const rangePick = (i) => {
    const from = lastPickRef.current == null ? i : lastPickRef.current;
    const lo = Math.min(from, i), hi = Math.max(from, i);
    for (let k = lo; k <= hi; k++) {
      const it = items[k];
      // add-only across the range, like the DC's Set union
      if (it && !selectedRef.current.has(it.media_id)) toggleSelected(it.media_id);
    }
    lastPickRef.current = i;
  };

  /* Drag-select: rubber-band over the grid while Select mode is on. The
     checkboxes still work; this is additive. Live hits paint locally while
     dragging; mouseup commits the replacement through App's toggle. */
  const [marquee, setMarquee] = useState(null);       // {x,y,w,h} for the band
  const [marqueeHits, setMarqueeHits] = useState(null); // Set<media_id> | null
  const startMarquee = (ev) => {
    if (!selectMode || ev.button !== 0) return;
    const grid = gridRef.current;
    if (!grid) return;
    ev.preventDefault();
    const base = { x: ev.clientX, y: ev.clientY };
    let dragged = false;
    let hits = new Set();
    const move = (e) => {
      const r = {
        x: Math.min(base.x, e.clientX), y: Math.min(base.y, e.clientY),
        w: Math.abs(e.clientX - base.x), h: Math.abs(e.clientY - base.y),
      };
      if (r.w > 4 || r.h > 4) dragged = true;
      if (!dragged) return; // under the 4px threshold it's still just a click
      hits = new Set();
      Array.prototype.forEach.call(grid.children, (el, i) => {
        const b = el.getBoundingClientRect();
        if (b.right > r.x && b.left < r.x + r.w && b.bottom > r.y && b.top < r.y + r.h) {
          const it = items[i];
          if (it) hits.add(it.media_id);
        }
      });
      setMarquee(r);
      setMarqueeHits(new Set(hits));
    };
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      if (dragged) {
        // The browser fires a click after the drag — swallow it once, or it
        // would toggle the card under the pointer straight back off.
        const eat = (e) => {
          e.stopPropagation(); e.preventDefault();
          window.removeEventListener("click", eat, true);
        };
        window.addEventListener("click", eat, true);
        // Commit: the marquee replaces the selection within this page.
        const cur = selectedRef.current;
        items.forEach((it) => {
          if (hits.has(it.media_id) !== cur.has(it.media_id)) toggleSelected(it.media_id);
        });
      }
      setMarquee(null);
      setMarqueeHits(null);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };

  /* Details straight from the thumbnail. App wires openDetails to the Lightbox
     but does not (yet) pass it here — so until it does, bridge through the URL
     contract App already owns: push /next?image=<mid> and fire popstate, which
     App's own listener reads back into state. Same destination, no new API. */
  const goDetails = (mid) => {
    if (typeof onOpenDetails === "function") { onOpenDetails(mid); return; }
    window.history.pushState({}, "", "/next?image=" + encodeURIComponent(mid));
    window.dispatchEvent(new PopStateEvent("popstate"));
  };

  return (
    <div className={"gridwrap" + (blur ? " mgg-blur" : "") + (selectMode ? " mgg-selecting" : "")}>
      {/* The separator bar the classic had between the controls and the grid:
          count left, browsing tip right (verbatim from master — the owner missed
          it, and it does real work giving the grid air from the header instead of
          the cards butting straight into the strip). */}
      <div className="tipbar">
        {total != null && (
          <span className="tb-count">
            {Number(total).toLocaleString()} match{total === 1 ? "" : "es"}
          </span>
        )}
        <span className="sp" />
        <span className="tb-tip">
          tip: click an image to open the lightbox · arrow keys to browse · F for slideshow
        </span>
      </div>

      {marquee && (
        <div
          className="mgg-marquee"
          style={{ left: marquee.x, top: marquee.y, width: marquee.w, height: marquee.h }}
        />
      )}

      <div
        ref={gridRef}
        className="mgg-grid"
        aria-busy={loading}
        onMouseDown={startMarquee}
        style={thumb ? { "--thumb": thumb + "px" } : undefined}
      >
        {items.map((it, i) => {
          // While a marquee drags, the band IS the selection (live replace);
          // otherwise the App-owned Set paints.
          const isSel = marqueeHits ? marqueeHits.has(it.media_id) : selected.has(it.media_id);
          const fname = it.filename || "";
          const shortName = fname.length > 22 ? fname.slice(0, 10) + "…" + fname.slice(-9) : fname;
          const badge = it.is_video ? "VIDEO" : (it.source ? String(it.source).toUpperCase() : "");
          const pillClass = it.is_video
            ? " video"
            : String(it.source || "").toLowerCase() === "local" ? " local" : "";
          return (
            <figure
              key={it.media_id}
              className={
                "mgg-card" +
                (it.is_nsfw ? " nsfw" : "") +
                (isSel ? " sel" : "")
              }
              /* shift held at press = range coming: stop the native text
                 selection before it starts */
              onMouseDown={(ev) => { if (ev.shiftKey) ev.preventDefault(); }}
              /* plain click → Lightbox; shift = range, ctrl/⌘ = toggle (both
                 with Select OFF); Select ON = every click selects */
              onClick={(ev) => {
                if (ev.shiftKey) { rangePick(i); return; }
                if (ev.ctrlKey || ev.metaKey) { togglePick(i); return; }
                if (selectMode) { togglePick(i); return; }
                openLightbox(i);
              }}
            >
              <img className="mgg-art" loading="lazy" draggable={false} src={it.thumb} alt="" />
              <span className="mgg-top">
                {/* the checkbox always single-toggles — no mode needed */}
                <button
                  type="button"
                  className="mgg-check"
                  title="Select this one"
                  aria-pressed={isSel}
                  onClick={(ev) => { ev.stopPropagation(); togglePick(i); }}
                >
                  {isSel ? "✓" : ""}
                </button>
                {badge ? (
                  <span className={"mgg-pill" + pillClass} title={"source: " + (it.is_video ? "video" : it.source)}>
                    {badge}
                  </span>
                ) : null}
              </span>
              {it.is_video ? <span className="mgg-vglyph">▶</span> : null}
              <figcaption className="mgg-cap">
                <span className="mgg-model">{it.model || "—"}</span>
                <span className="mgg-date">{it.date || ""}</span>
                {fname ? <span className="mgg-file" title={fname}>{shortName}</span> : null}
                <span className="mgg-caprow">
                  <Stars mediaId={it.media_id} rating={it.rating} onRate={onRate} />
                  <button
                    type="button" className="mgg-chip open" title="Open the lightbox"
                    onClick={(ev) => { ev.stopPropagation(); openLightbox(i); }}
                  >
                    Open
                  </button>
                  <button
                    type="button" className="mgg-chip ghost" title="Open the full record"
                    onClick={(ev) => { ev.stopPropagation(); goDetails(it.media_id); }}
                  >
                    Details
                  </button>
                </span>
              </figcaption>
            </figure>
          );
        })}
      </div>
      {loading && <div className="sentinel">summoning…</div>}
      {!loading && pages > 1 && (
        <PageBar page={page} pages={pages} go={go} />
      )}
    </div>
  );
}

/* Windowed page numbers with ellipses -- first, last, current ±2 -- because a
   35k-image library at 100/page is ~350 pages; a flat list would be absurd. */
function PageBar({ page, pages, go }) {
  const nums = [];
  const add = (n) => { if (!nums.includes(n)) nums.push(n); };
  add(1); add(pages);
  for (let d = -2; d <= 2; d++) { const n = page + d; if (n >= 1 && n <= pages) add(n); }
  nums.sort((a, b) => a - b);
  const withGaps = [];
  nums.forEach((n, i) => {
    if (i > 0 && n - nums[i - 1] > 1) withGaps.push("…" + n);
    withGaps.push(n);
  });
  return (
    <nav className="pagebar" aria-label="Pages">
      <button className="pg-nav" disabled={page <= 1} onClick={() => go(page - 1)}>‹ Prev</button>
      {withGaps.map((n) =>
        typeof n === "string" ? (
          <span key={n} className="pg-ellipsis">…</span>
        ) : (
          <button key={n} className={"pg-num" + (n === page ? " current" : "")}
            onClick={() => go(n)} aria-current={n === page ? "page" : undefined}>
            {n}
          </button>
        )
      )}
      <button className="pg-nav" disabled={page >= pages} onClick={() => go(page + 1)}>Next ›</button>
    </nav>
  );
}

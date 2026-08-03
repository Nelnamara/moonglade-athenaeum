import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import Stars from "./Stars.jsx";
import "../styles/grid.css";

/* The grid, refit to the Frontend Gallery DC (drift §9) and to LOOM MASONRY v1
   (design-side spec, grid-algorithm-spec.md / drift §18): SIZE-slider cell
   sizing via --thumb, reveal-on-hover caption slab with Open/Details chips,
   metallic source pills, and the full select grammar:

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
/* ---- Loom Masonry v1 (grid-algorithm-spec.md) --------------------------------
   Every constant here is the spec's, not a guess: 11px gap, 8px auto-rows (so a
   row step is 19px), display ratio clamped to .62–1.85, and a minimum 4-row span.
   The point of the whole thing: a card's SHAPE comes from its own image, so
   `cover` has nothing left to crop. Cropping survives in exactly one place --
   a true ratio outside the clamp (panoramas, ultra-talls) -- and those anchor
   high, because faces in this library sit top-of-frame. */
const GAP = 11;
const ROW_STEP = 19;          // grid-auto-rows 8px + the 11px gap
// R_MIN 0.55, not the spec's 0.62: 16:9 is 0.5625, and the spec's own stated
// intent is that only GENUINELY very-wide images (panoramas) crop -- a 0.62
// floor put every widescreen render in the library under the knife, which is
// exactly the "still cropping" the owner flagged in QA. Disclosed deviation;
// the number goes back to the design side for the spec to adopt.
const R_MIN = 0.55, R_MAX = 1.85;
const FEAT_R_MAX = 1.05;      // a feature slot wants square-ish, not tall
const FEAT_CADENCE = 9;       // one feature per 9 positions...
const FEAT_LOOKAHEAD = 12;    // ...chosen from the next 12 images in page order

const trueRatio = (it) => {
  const w = parseFloat(it.w), h = parseFloat(it.h);
  return w > 0 && h > 0 ? h / w : 1;   // dimensionless rows (old imports): square
};
const clampR = (r, hi) => Math.max(R_MIN, Math.min(hi, r));
const spanFor = (width, r) => Math.max(4, Math.round((width * r + GAP) / ROW_STEP));

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

  /* ---- Loom Masonry v1 layout (grid-algorithm-spec.md) ----
     Measure the grid's real pixel width so cols/colW match what the browser
     lays out, then produce `laid` -- the VISUAL-ORDER cell list (feature slots
     already swapped in) that BOTH the render and the marquee hit-test walk.
     Everything downstream indexes `laid`, never `items`, so DOM order and the
     select grammar stay consistent after the feature swaps. */
  const [gridW, setGridW] = useState(0);
  // useLayoutEffect + a synchronous first measure: a ResizeObserver's initial
  // callback is async and was landing AFTER the memo committed with width 0
  // (cols collapsed to 1, so no feature slots ever appeared). Measuring here,
  // before paint, seeds the real width; the observer then tracks live resizes.
  useLayoutEffect(() => {
    const el = gridRef.current;
    if (!el) return;
    const measure = () => setGridW(el.clientWidth);
    measure();
    if (typeof ResizeObserver !== "undefined") {
      const ro = new ResizeObserver(measure);
      ro.observe(el);
      return () => ro.disconnect();
    }
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  const laid = useMemo(() => {
    const tw = thumb || 210;
    const width = gridW || 0;
    // Padding is 12px each side (grid.css). cols from the spec's own formula.
    const inner = Math.max(0, width - 24);
    const cols = width ? Math.max(1, Math.floor((inner + GAP) / (tw + GAP))) : 1;
    const colW = width ? (inner - (cols - 1) * GAP) / cols : tw;

    const arr = items.slice();                 // shallow: we only REORDER refs
    const feature = new Array(arr.length).fill(false);
    if (cols >= 3) {
      const offset = ((page % 3) + 2) % FEAT_CADENCE;
      for (let p = 0; p < arr.length; p++) {
        if (p % FEAT_CADENCE !== offset) continue;
        // squarest (min |r-1|) non-video image in the next lookahead window
        let best = -1, bestScore = Infinity;
        const end = Math.min(p + FEAT_LOOKAHEAD, arr.length);
        for (let k = p; k < end; k++) {
          if (arr[k].is_video) continue;
          const s = Math.abs(trueRatio(arr[k]) - 1);
          if (s < bestScore) { bestScore = s; best = k; }
        }
        if (best >= 0) {
          if (best !== p) { const t = arr[p]; arr[p] = arr[best]; arr[best] = t; }
          feature[p] = true;
        }
      }
    }
    return arr.map((it, i) => {
      const feat = feature[i];
      const w = feat ? (2 * colW + GAP) : colW;
      const tr = trueRatio(it);
      const span = spanFor(w, clampR(tr, feat ? FEAT_R_MAX : R_MAX));
      return { it, feat, colspan: feat ? 2 : 1, span, crop: tr > R_MAX || tr < R_MIN };
    });
  }, [items, gridW, thumb, page]);

  // The Lightbox indexes `items` in its own untouched catalog order (its own
  // filmstrip/prev-next paging depends on that) -- but `laid` reorders a copy
  // for the feature-slot swap above, so a card's position in `laid` can differ
  // from its real position in `items`. openLightbox() must always resolve
  // through this map, never pass the bare `laid` index straight through, or
  // clicking a swapped-in feature card opens whatever item originally sat at
  // that slot instead (owner-reported 2026-08-03: wrong image opens, "usually
  // the large ones" -- the feature slots are exactly where the swap happens).
  const origIndexByMid = useMemo(() => {
    const m = new Map();
    items.forEach((it, idx) => m.set(it.media_id, idx));
    return m;
  }, [items]);

  // The shift-range anchor is an INDEX into the current page's laid cells --
  // carrying it across a page flip would range-add against a stale anchor.
  useEffect(() => { lastPickRef.current = null; }, [items]);

  const togglePick = (i) => {
    lastPickRef.current = i;
    toggleSelected(laid[i].it.media_id);
  };
  const rangePick = (i) => {
    const from = lastPickRef.current == null ? i : lastPickRef.current;
    const lo = Math.min(from, i), hi = Math.max(from, i);
    for (let k = lo; k <= hi; k++) {
      const it = laid[k] && laid[k].it;
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
          const it = laid[i] && laid[i].it;   // DOM order === laid order
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
        laid.forEach(({ it }) => {
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
        {laid.map((cell, i) => {
          const it = cell.it;
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
              // Loom Masonry v1: aspect-true row span; a feature spans 2 cols.
              style={{
                gridRow: "span " + cell.span,
                gridColumn: cell.colspan > 1 ? "span " + cell.colspan : undefined,
              }}
              className={
                "mgg-card" +
                (it.is_nsfw ? " nsfw" : "") +
                (isSel ? " sel" : "") +
                (cell.feat ? " feat" : "")
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
                openLightbox(origIndexByMid.get(it.media_id));
              }}
            >
              {/* Only out-of-clamp ratios (panoramas, ultra-talls) crop at all;
                  anchor them high -- faces in this library's portrait art sit
                  top-of-frame (grid-algorithm-spec §1). */}
              <img className="mgg-art" loading="lazy" draggable={false} src={it.thumb} alt=""
                style={cell.crop ? { objectPosition: "50% 12%" } : undefined} />
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
                    onClick={(ev) => { ev.stopPropagation(); openLightbox(origIndexByMid.get(it.media_id)); }}
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

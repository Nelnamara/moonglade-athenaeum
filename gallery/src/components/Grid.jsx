import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { localDay, localDayTime } from "../gen/dates.js";
import { fetchSiblings } from "../api.js";
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
/* ---- Layout modes (drift §46/§47) --------------------------------------------
   The Filters-tray picker re-lays the SAME cards four ways (App owns the mode in
   mg_gallery_layout, hands it here as `layout`). Masonry is the aspect-true base
   above; Grid/Hero/Timeline add the geometry below, following the workshop
   `Gallery Layouts Workshop.dc.html` math but on the SHIPPED grid's constants
   (GAP 11, 8px rows) rather than the workshop's GAP 12, per the integration
   brief. */
const GRID_ASPECT = 3 / 4;    // uniform Grid/Hero cells are 4:3 landscape (h = w·3/4)
// Grid / Hero (drift §46). "Wide" (spans 2 cells instead of being gutted) triggers at
// display ratio w/h >= 2.2, i.e. trueRatio (h/w) <= 1/2.2 — expressed as trueRatio so it
// reuses the one ratio helper. Hero features the newest of every HERO_EVERY tiles at 3:2;
// a video never takes a feature slot.
const WIDE_TR = 1 / 2.2;
const HERO_EVERY = 12;

const trueRatio = (it) => {
  const w = parseFloat(it.w), h = parseFloat(it.h);
  return w > 0 && h > 0 ? h / w : 1;   // dimensionless rows (old imports): square
};
const clampR = (r, hi) => Math.max(R_MIN, Math.min(hi, r));
const spanFor = (width, r) => Math.max(4, Math.round((width * r + GAP) / ROW_STEP));
// Fixed pixel height → row span on the same 8px/11gap grain (Grid/Hero/Timeline
// cells know their height directly, unlike masonry which derives it from ratio).
const spanForH = (hpx) => Math.max(1, Math.round((hpx + GAP) / ROW_STEP));

/* Timeline banding (drift §47): Today · Yesterday · then YYYY-MM, newest first.
   The day is the viewer's LOCAL day from the row's full created_at (gen/dates.js);
   the server's `date` (a UTC slice) is only the fallback for rows with no timestamp.
   A missing date (very old imports) falls into an "Undated" band, last. */
function todayYesterday() {
  const pad = (n) => String(n).padStart(2, "0");
  const fmt = (d) => d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  const t = new Date();
  const y = new Date(t);
  y.setDate(y.getDate() - 1);
  return { today: fmt(t), yesterday: fmt(y) };
}
function bandFor(date, today, yesterday) {
  if (!date) return { key: "undated", label: "Undated", tier: -1, monthKey: "" };
  if (date === today) return { key: "today", label: "Today", tier: 3, monthKey: date };
  if (date === yesterday) return { key: "yday", label: "Yesterday", tier: 2, monthKey: date };
  const ym = String(date).slice(0, 7);
  return { key: ym, label: ym, tier: 1, monthKey: ym };
}

// Smallest thumb size (the SIZE slider value) at which the Sibling Strip renders. The
// default is 210; the slider floor is 152. Measured: a strip card's slab overflows the
// fixed-height grid cell from ~172 down, so the gate sits above that with margin.
const STRIP_MIN_THUMB = 190;

export default function Grid({
  items, total, loading, page, pages, goToPage,
  blur, thumb, layout = "masonry",
  selectMode, selected, toggleSelected, openLightbox, onRate,
  onOpenDetails, onContextMenu,
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

  /* ---- layout measurement (grid-algorithm-spec.md) ----
     Measure the card container's real pixel width so cols/colW match what the
     browser lays out. `gridRef` is the marquee/measurement container for EVERY
     layout: the .mgg-grid for masonry/grid/hero, the tiles column for timeline
     (narrower — it shares the row with the 92px jump rail), so colW comes out
     right for whichever is mounted. Re-runs on `layout` change because a
     different element mounts. */
  const [gridW, setGridW] = useState(0);
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
  }, [layout]);

  /* The VISUAL-ORDER cell list, plus (timeline only) the band index. Both the
     render and the marquee hit-test walk `cells`; everything indexes it, never
     `items`, so DOM order and the select grammar stay consistent whatever the
     feature-swap / banding did. Returns { cells, bands } — bands is null for the
     flat (non-timeline) layouts. */
  const { cells, bands } = useMemo(() => {
    const tw = thumb || 210;
    const width = gridW || 0;
    // The measured element differs by layout: the .mgg-grid (12px padding each
    // side → subtract 24) for masonry/grid/hero, or the .mgg-tl-cols tiles pane
    // (no inner padding; the 12px gutter lives on .mgg-timeline, outside it) for
    // timeline. cols from the spec's own formula either way.
    const inner = Math.max(0, width - (layout === "timeline" ? 0 : 24));
    const cols = width ? Math.max(1, Math.floor((inner + GAP) / (tw + GAP))) : 1;
    const colW = width ? (inner - (cols - 1) * GAP) / cols : tw;

    // ---- MASONRY (current, aspect-true, feature slots) — unchanged ----
    if (layout === "masonry") {
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
      const out = arr.map((it, i) => {
        const feat = feature[i];
        const w = feat ? (2 * colW + GAP) : colW;
        const tr = trueRatio(it);
        const span = spanFor(w, clampR(tr, feat ? FEAT_R_MAX : R_MAX));
        return { it, feat, colspan: feat ? 2 : 1, span, crop: tr > R_MAX || tr < R_MIN };
      });
      return { cells: out, bands: null };
    }

    // ---- GRID (uniform 4:3, smart-cropped; wide art spans 2 cols) ----
    // Crop v1 is a fixed top-center anchor (object-position 50% 12%, applied in
    // the render off `cell.crop`) — the SAME anchor masonry already uses for its
    // out-of-clamp art. There is NO saliency/focal data in the catalog, so true
    // subject-crop is a future backend (drift §46, workshop STAND-INS note); do
    // not invent it here.
    if (layout === "grid") {
      const cellH = colW * GRID_ASPECT;          // 4:3 landscape
      const span = spanForH(cellH);
      const out = items.map((it) => {
        const wide = trueRatio(it) <= WIDE_TR;     // banner/panorama → 2 cols, not gutted
        return { it, feat: false, colspan: wide ? 2 : 1, span, crop: true };
      });
      return { cells: out, bands: null };
    }

    // ---- HERO (newest = large 3:2 feature every 12 tiles; rest = 4:3 grid) ----
    // items arrive newest-first (default sort), so i === 0 is the newest and
    // i % 12 === 0 repeats the feature. A VIDEO never takes a hero slot — it just
    // falls back to a normal cell (drift §46 / workshop); no look-ahead promotion.
    if (layout === "hero") {
      const cellH = colW * GRID_ASPECT;
      const gridSpan = spanForH(cellH);
      const out = items.map((it, i) => {
        const hero = (i % HERO_EVERY === 0) && !it.is_video;
        const wide = trueRatio(it) <= WIDE_TR;
        if (hero) {
          const wpx = colW * 2 + GAP;             // hero spans 2 cols
          const hpx = wpx / 1.5;                   // 3:2 feature (workshop hpx = wpx/1.5)
          return { it, feat: true, colspan: 2, span: spanForH(hpx), crop: true };
        }
        return { it, feat: false, colspan: wide ? 2 : 1, span: gridSpan, crop: true };
      });
      return { cells: out, bands: null };
    }

    // ---- TIMELINE (date-banded, newest first, no-crop; edge jump rail) ----
    // Group into bands, order the bands newest-first (Today, Yesterday, then
    // months desc, Undated last), then flatten back into ONE cell list in that
    // banded order so shift-range over the flat indices stays visually
    // contiguous. Tiles wrap aspect-true (like masonry), single column each.
    const { today, yesterday } = todayYesterday();
    const groups = new Map();
    const order = [];
    items.forEach((it) => {
      const b = bandFor(localDay(it.created_at) || it.date, today, yesterday);
      let g = groups.get(b.key);
      if (!g) {
        g = { key: b.key, label: b.label, tier: b.tier, monthKey: b.monthKey, list: [] };
        groups.set(b.key, g);
        order.push(g);
      }
      g.list.push(it);
    });
    order.sort((a, bb) => {
      if (a.tier !== bb.tier) return bb.tier - a.tier;            // Today > Yesterday > months > Undated
      return a.monthKey < bb.monthKey ? 1 : a.monthKey > bb.monthKey ? -1 : 0; // newest month first
    });
    const flat = [];
    const outBands = order.map((g) => {
      const start = flat.length;
      g.list.forEach((it) => {
        const tr = trueRatio(it);
        const hpx = colW * clampR(tr, R_MAX);
        flat.push({ it, feat: false, colspan: 1, span: spanForH(hpx), crop: tr > R_MAX || tr < R_MIN });
      });
      return { key: g.key, label: g.label, count: g.list.length, start, end: flat.length };
    });
    return { cells: flat, bands: outBands };
  }, [items, gridW, thumb, page, layout]);

  // The Lightbox indexes `items` in its own untouched catalog order (its own
  // filmstrip/prev-next paging depends on that) -- but `cells` reorders a copy
  // for the feature-slot swap / banding above, so a card's position in `cells`
  // can differ from its real position in `items`. openLightbox() must always
  // resolve through this map, never pass the bare cell index straight through, or
  // clicking a swapped-in feature card opens whatever item originally sat at
  // that slot instead (owner-reported 2026-08-03: wrong image opens, "usually
  // the large ones" -- the feature slots are exactly where the swap happens).
  const origIndexByMid = useMemo(() => {
    const m = new Map();
    items.forEach((it, idx) => m.set(it.media_id, idx));
    return m;
  }, [items]);

  /* ---- Sibling Strip data (#30, direction E): ONE batched POST per page ----
     Collect the page's distinct non-empty task_ids and ask /api/siblings ONCE;
     never per card. `siblingsSeq` is the epoch guard (the same discipline as
     GenerateDrawer's prefillSeq): a fast page flip retires the older request
     wholesale, so the previous page's strips can never paint over this one.
     Failure -> no strips, no toast: the strip is decoration. */
  const [siblings, setSiblings] = useState({});
  const siblingsSeq = useRef(0);
  useEffect(() => {
    const my = ++siblingsSeq.current;
    setSiblings({});
    const taskIds = [];
    const seen = new Set();
    items.forEach((it) => {
      const t = it.task_id ? String(it.task_id) : "";
      if (t && !seen.has(t)) { seen.add(t); taskIds.push(t); }
    });
    if (!taskIds.length) return;
    fetchSiblings(taskIds).then((d) => {
      if (siblingsSeq.current !== my) return;   // superseded -- a newer page won
      setSiblings((d && d.by_task) || {});
    });
  }, [items]);

  // The shift-range anchor is an INDEX into the current page's cells -- carrying
  // it across a page flip (or a layout re-lay, which reorders cells) would
  // range-add against a stale anchor.
  useEffect(() => { lastPickRef.current = null; }, [items, layout]);

  const togglePick = (i) => {
    lastPickRef.current = i;
    toggleSelected(cells[i].it.media_id);
  };
  const rangePick = (i) => {
    const from = lastPickRef.current == null ? i : lastPickRef.current;
    const lo = Math.min(from, i), hi = Math.max(from, i);
    for (let k = lo; k <= hi; k++) {
      const it = cells[k] && cells[k].it;
      // add-only across the range, like the DC's Set union
      if (it && !selectedRef.current.has(it.media_id)) toggleSelected(it.media_id);
    }
    lastPickRef.current = i;
  };

  /* Drag-select: rubber-band over the grid while Select mode is on. The
     checkboxes still work; this is additive. Live hits paint locally while
     dragging; mouseup commits the replacement through App's toggle. Hit-testing
     reads each card's data-laid-index attribute rather than DOM child order, so
     it works whether the cards live in one grid (masonry/grid/hero) or across
     several band grids (timeline). */
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
      grid.querySelectorAll(".mgg-card").forEach((el) => {
        const idx = Number(el.getAttribute("data-laid-index"));
        const b = el.getBoundingClientRect();
        if (b.right > r.x && b.left < r.x + r.w && b.bottom > r.y && b.top < r.y + r.h) {
          const it = cells[idx] && cells[idx].it;
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
        cells.forEach(({ it }) => {
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
    window.history.pushState({}, "", "/?image=" + encodeURIComponent(mid));
    window.dispatchEvent(new PopStateEvent("popstate"));
  };

  /* ---- Timeline jump rail: sticky vertical band list; click scrolls the tiles
     pane to that band. The pane is an internal scroll context (grid.css) so the
     sticky band headers + rail clear the app's own sticky header — the
     workshop's pattern; page-scroll would slide the headers behind the banner.
     `activeBand` follows the scroll so the rail marks where you are. ---- */
  const bandRefs = useRef({});
  const [activeBand, setActiveBand] = useState(null);
  const scrollToBand = (key) => {
    const el = bandRefs.current[key];
    const cont = gridRef.current;
    if (el && cont) cont.scrollTo({ top: Math.max(0, el.offsetTop - 4), behavior: "smooth" });
  };
  useEffect(() => {
    if (!bands) { setActiveBand(null); return undefined; }
    const cont = gridRef.current;
    if (!cont) return undefined;
    const onScroll = () => {
      const top = cont.scrollTop;
      let cur = bands[0] && bands[0].key;
      for (const b of bands) {
        const el = bandRefs.current[b.key];
        if (el && el.offsetTop - 10 <= top) cur = b.key; else break;
      }
      setActiveBand(cur);
    };
    onScroll();
    cont.addEventListener("scroll", onScroll, { passive: true });
    return () => cont.removeEventListener("scroll", onScroll);
  }, [bands]);

  /* One card renderer for EVERY layout, so the affordances (checkbox, source
     pill, video glyph, caption with stars + Open/Details, the full click
     grammar) are byte-identical across masonry/grid/hero/timeline — drift §46's
     "stay identical across all layouts" contract. `i` is the flat cells index;
     it drives the select grammar and marquee mapping (data-laid-index). */
  const renderCard = (cell, i) => {
    const it = cell.it;
    // While a marquee drags, the band IS the selection (live replace);
    // otherwise the App-owned Set paints.
    const isSel = marqueeHits ? marqueeHits.has(it.media_id) : selected.has(it.media_id);
    const badge = it.is_video ? "VIDEO" : (it.source ? String(it.source).toUpperCase() : "");
    // Sibling Strip (#30, direction E): the task's outputs, self lit, the rest dimmed.
    // Only when the task has >= 2 members (the API already omits the rest). More than
    // four -> four and a "+N"; self always sits among the four shown.
    const sibs = it.task_id ? siblings[it.task_id] : null;
    let strip = null;
    // Owner call (a), 2026-08-22: below STRIP_MIN_THUMB the fixed-height grid/hero cell
    // can no longer hold the slab + a strip (it clips the stamp at the card top), and at
    // that size 30px sibling thumbs are noise anyway. The stamp -- the part that fixes
    // the naming problem -- survives at every size; only the strip steps aside.
    if (Array.isArray(sibs) && sibs.length >= 2 && (thumb || 210) >= STRIP_MIN_THUMB) {
      const shown = sibs.slice(0, 4);
      if (sibs.length > 4 && !shown.some((s) => s.media_id === it.media_id)) {
        const self = sibs.find((s) => s.media_id === it.media_id);
        if (self) shown[3] = self;
      }
      strip = (
        <span className="mgg-strip">
          {shown.map((s) => (
            <img
              key={s.media_id} src={s.thumb} alt="" loading="lazy" draggable={false}
              className={s.media_id === it.media_id ? "self" : undefined}
            />
          ))}
          {sibs.length > 4 ? <span className="more">+{sibs.length - 4}</span> : null}
        </span>
      );
    }
    const pillClass = it.is_video
      ? " video"
      : String(it.source || "").toLowerCase() === "local" ? " local" : "";
    return (
      <figure
        key={it.media_id}
        data-laid-index={i}
        // aspect-true / uniform-cell row span; a feature or wide cell spans 2 cols.
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
        /* right-click → the 5-action context menu (App owns it). preventDefault
           suppresses the browser's own menu. */
        onContextMenu={(ev) => {
          if (!onContextMenu) return;
          ev.preventDefault();
          onContextMenu(it.media_id, it.thumb, ev.clientX, ev.clientY, !!it.is_video);
        }}
        /* plain click → Lightbox; shift = range, ctrl/⌘ = toggle (both
           with Select OFF); Select ON = every click selects */
        onClick={(ev) => {
          if (ev.shiftKey) { rangePick(i); return; }
          if (ev.ctrlKey || ev.metaKey) { togglePick(i); return; }
          if (selectMode) { togglePick(i); return; }
          openLightbox(origIndexByMid.get(it.media_id));
        }}
      >
        {/* Only cropped cells anchor high: masonry's out-of-clamp panoramas /
            ultra-talls, and every uniform Grid/Hero cell (cover-filled to 4:3 /
            3:2). Top-center, because faces in this library's portrait art sit
            top-of-frame (grid-algorithm-spec §1; drift §46 crop v1). */}
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
          {/* Accession Stamp (#30, direction A; pixel source: the owner's locked
              "Placard identity -- five directions" artifact). The title slot holds
              ONLY a real title the piece was given -- never the filename, never
              anything machine-derived (the review's hard condition). Line 1 is the
              local day · time, line 2 the model (uppercased by CSS), flagged
              "not grouped" when the row has no task to belong to. */}
          {it.title ? <span className="mgg-title">{it.title}</span> : null}
          <span className="mgg-stamp lead">{localDayTime(it.created_at) || it.date || ""}</span>
          <span className="mgg-stamp">{(it.model || "no model") + (it.task_id ? "" : " · not grouped")}</span>
          {strip}
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
  };

  const isTimeline = layout === "timeline" && bands;

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

      {isTimeline ? (
        /* Timeline (drift §47): date-banded wall + edge JUMP-TO rail. */
        <div className="mgg-timeline">
          <div
            ref={gridRef}
            className="mgg-tl-cols"
            aria-busy={loading}
            onMouseDown={startMarquee}
          >
            {bands.map((band) => (
              <section
                key={band.key}
                className="mgg-tl-band"
                ref={(el) => { bandRefs.current[band.key] = el; }}
              >
                <div className="mgg-tl-head">
                  <span className="mgg-tl-title">{band.label}</span>
                  <span className="mgg-tl-count">{band.count} item{band.count === 1 ? "" : "s"}</span>
                  <span className="mgg-tl-rule" />
                </div>
                <div className="mgg-grid mgg-tl-grid" style={thumb ? { "--thumb": thumb + "px" } : undefined}>
                  {cells.slice(band.start, band.end).map((cell, k) => renderCard(cell, band.start + k))}
                </div>
              </section>
            ))}
          </div>
          <nav className="mgg-tl-rail" aria-label="Jump to date band">
            <div className="mgg-tl-railhead">JUMP TO</div>
            {bands.map((band) => (
              <button
                key={band.key}
                type="button"
                className={"mgg-tl-jump" + (activeBand === band.key ? " on" : "")}
                onClick={() => scrollToBand(band.key)}
                title={band.label + " · " + band.count + " item" + (band.count === 1 ? "" : "s")}
              >
                {band.label}
              </button>
            ))}
          </nav>
        </div>
      ) : (
        <div
          ref={gridRef}
          className="mgg-grid"
          aria-busy={loading}
          onMouseDown={startMarquee}
          style={thumb ? { "--thumb": thumb + "px" } : undefined}
        >
          {cells.map((cell, i) => renderCard(cell, i))}
        </div>
      )}

      {loading && <div className="sentinel">summoning…</div>}
      {!loading && pages > 1 && (
        <>
          <PageBar page={page} pages={pages} go={go} />
          {/* Frontend Gallery.dc.html:205-208 -- "Page X of Y · N per page · N items",
              missing with no disclosed reason (unlike the deliberately-removed "Load N
              more" button next to it, which stays gone -- a real owner decision, see this
              file's header comment). Real per-page count is items.length, the actual
              number of rows this page loaded, not a hardcoded page-size constant. */}
          <div className="pagecaption">
            Page {page} of {pages} · {items.length} per page · {Number(total).toLocaleString()} item{total === 1 ? "" : "s"}
          </div>
        </>
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

import React, { useRef, useState } from "react";
import { thumbSrc } from "../lib/phoneCore.js";
import "../styles/phone-q.css";

/* The 2-column staggered tile grid (design spec: Moonglade Mobile.dc.html
   gridStyle/colStyle/colOffStyle/capStyle, lines 89-106 & 930-934) -- deliberately
   NOT desktop Grid.jsx's Loom Masonry v1 (ResizeObserver width measurement,
   feature-slot swapping, marquee drag-select): this increment's brief calls for
   "a simpler CSS grid/flex approach", and the DC's own staggering is simpler
   still than that -- two plain flex columns (odd/even split by index) with the
   second column offset 22px down, each tile sized by its own real aspect-ratio
   (`aspect-ratio: w/h`, CSS-only, no JS measuring at all). Dimensionless items
   (no w/h on old imports) fall back to a square tile, matching Grid.jsx's own
   `trueRatio` fallback.

   SELECTION GESTURE (this increment's brief, point 4 -- "a genuinely NEW mobile
   gesture layer... check the design file first for whether it specifies the
   exact gesture"): Moonglade Mobile.dc.html's own tap(i) is select-mode-aware
   but says nothing about ARMING select mode from the grid itself -- entering it
   is only ever the toolbar's "Select" pill (GalleryMobile.jsx). This layer adds
   the pattern the brief explicitly sanctions as the default absent a DC spec:
   long-press (480ms, cancelled by >10px of movement so a scroll is never
   mistaken for a hold) arms select mode AND selects the pressed tile; a plain
   tap toggles selection while already in select mode; a plain tap while NOT in
   select mode opens the LIGHTBOX (GalleryMobile.jsx's onTapView -> LightboxMobile),
   per Moonglade Mobile.dc.html:988-990's own tap(i) and issue #35 -- an earlier
   revision of this very comment claimed tap->Details was the design and the owner
   corrected it ("That was NOT the design"). Details is one tap away via the
   lightbox's "Details ›" pill; this component still doesn't need to know which
   viewer opens -- it just calls onTapView. Built on Pointer Events
   (not touch-only) so it also works with a
   real mouse on a narrow desktop browser window, which is how this surface gets
   exercised by both a human and Playwright.

   SESSION Q (2026-09-29), ADDITIVE -- the grid above is untouched when none of the new props is set:
     layout="feed" (Q3)  one picture per row, edge to edge at its true aspect, prompt and stars over
                         the foot; the same tap / long-press / select gestures as a tile.
     newCount / newLabel (Q5)  the lavender "N new since HH:MM" rule after the first N pictures. The
                         grid is cut in two at the rule (the page does the same), each half keeping the
                         two-column stagger; the feed is one list with the rule in it.
     cols (Q4)           how many columns the run of pictures is dealt across: 2 upright, 4 sideways
                         (3 under 700 px wide), laid straight into a grid the way the page draws it.
                         Every picture wears data-mid, which is how a turn of the phone finds the one
                         at the top of the view again (hooks/useScrollAnchor.js).
     saver (Q7)          256 px thumbnails, and the page's small tag on each tile ("256 px", or
                         "▶ paused" on a video). Full size is the Lightbox's business, not this grid's. */

const LONG_PRESS_MS = 480;
const MOVE_CANCEL_PX = 10;

function trueRatio(it) {
  const w = parseFloat(it.w), h = parseFloat(it.h);
  return w > 0 && h > 0 ? w / h : 1;
}

function Tile({ it, selectMode, selected, pressing, handlers, saver, feed }) {
  const caption = (it.prompt || "").trim().slice(0, 70) || it.model || "";
  const stars = it.rating > 0 ? "★".repeat(Math.min(5, it.rating)) : "";
  const tag = saver && !selectMode ? (it.is_video ? "▶ paused" : "256 px") : "";
  return (
    <figure
      className={"glm-tile" + (feed ? " glm-tile-feed" : "") + (selected ? " sel" : "") + (pressing ? " pressing" : "")}
      style={{ aspectRatio: trueRatio(it), "--ar": trueRatio(it) }}
      data-mid={it.media_id}
      onContextMenu={(e) => e.preventDefault()}
      {...handlers}
    >
      <img className="glm-tile-img" src={thumbSrc(it.thumb, saver)} alt="" loading="lazy" draggable={false} />
      {it.is_video && !tag ? <span className="glm-tile-vid" aria-hidden="true">▶</span> : null}
      {tag ? <span className="glm-tile-tag" aria-hidden="true">{tag}</span> : null}
      {selectMode ? (
        <span className={"glm-tile-chk" + (selected ? " on" : "")} aria-hidden="true">
          {selected ? "✓" : ""}
        </span>
      ) : null}
      {feed ? (
        (caption || stars) ? (
          <figcaption className="glm-tile-cap">
            <span className="glm-tile-prompt">{(it.prompt || "").trim() || it.model || ""}</span>
            {stars ? <><span className="glm-tile-sep" aria-hidden="true">{"·"}</span><span className="glm-tile-stars">{stars}</span></> : null}
          </figcaption>
        ) : null
      ) : caption ? (
        <figcaption className="glm-tile-cap">
          <span className="glm-tile-model">{caption}</span>
          {it.date ? <span className="glm-tile-date">{it.date}</span> : null}
        </figcaption>
      ) : null}
    </figure>
  );
}

export default function GalleryGridMobile({
  items, loading, selectMode, selected, toggleSelected, onArmSelect, onTapView,
  layout = "grid", saver = false, newCount = 0, newLabel = "", cols = 2,
}) {
  const pressRef = useRef(null); // {mid, timer, x, y, moved, armed}
  const [pressingId, setPressingId] = useState(null);

  const clearPress = () => {
    if (pressRef.current) clearTimeout(pressRef.current.timer);
    pressRef.current = null;
    setPressingId(null);
  };

  const makeHandlers = (mid) => ({
    onPointerDown: (e) => {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      clearPress();
      const st = { mid, x: e.clientX, y: e.clientY, moved: false, armed: false, timer: null };
      st.timer = setTimeout(() => {
        st.armed = true;
        setPressingId(null);
        onArmSelect(mid);
      }, LONG_PRESS_MS);
      pressRef.current = st;
      setPressingId(mid);
    },
    onPointerMove: (e) => {
      const st = pressRef.current;
      if (!st || st.mid !== mid || st.armed) return;
      if (Math.abs(e.clientX - st.x) > MOVE_CANCEL_PX || Math.abs(e.clientY - st.y) > MOVE_CANCEL_PX) {
        clearTimeout(st.timer);
        st.moved = true;
        setPressingId(null);
      }
    },
    onPointerUp: () => {
      const st = pressRef.current;
      clearPress();
      if (!st || st.mid !== mid || st.armed || st.moved) return;
      if (selectMode) toggleSelected(mid);
      else onTapView(mid);
    },
    onPointerCancel: clearPress,
    onPointerLeave: () => {
      const st = pressRef.current;
      if (st && st.mid === mid && !st.armed) { clearTimeout(st.timer); st.moved = true; setPressingId(null); }
    },
  });

  if (!loading && items.length === 0) {
    return <div className="glm-empty">No matches — try clearing a filter.</div>;
  }

  const feed = layout === "feed";
  const tile = (it) => (
    <Tile key={it.media_id} it={it} selectMode={selectMode} selected={selected.has(it.media_id)}
      pressing={pressingId === it.media_id} handlers={makeHandlers(it.media_id)} saver={saver} feed={feed} />
  );
  // One run of pictures. Upright it is the DC's own stagger: two flex columns, the second offset 22px
  // down. Sideways (Q4) it is the Phone Handoff's landscape grid: 4 columns (3 on the narrow phones) of
  // tiles laid straight into a CSS grid in reading order, rows aligned, no stagger -- as the page draws it.
  const grid = (list, key) => {
    if (cols > 2) {
      return (
        <div key={key} className={"glm-grid glm-grid-rows" + (loading ? " loading" : "")}
          style={{ gridTemplateColumns: "repeat(" + cols + ", minmax(0, 1fr))" }}>
          {list.map(tile)}
        </div>
      );
    }
    const left = list.filter((_, i) => i % 2 === 0);
    const right = list.filter((_, i) => i % 2 === 1);
    return (
      <div key={key} className={"glm-grid" + (loading ? " loading" : "")}>
        <div className="glm-col">{left.map(tile)}</div>
        <div className="glm-col glm-col-off">{right.map(tile)}</div>
      </div>
    );
  };
  const rule = newCount > 0 && newCount <= items.length && newLabel;
  // Q5: the rule goes after the first newCount pictures, in either layout. When every loaded picture
  // is new (a capped count) the rule closes the list.
  const fresh = rule ? items.slice(0, newCount) : [];
  const older = rule ? items.slice(newCount) : items;
  const ruleEl = rule ? (
    <div key="rule" className="glm-newrule" role="separator" aria-label={newLabel}>
      <i /><span>{newLabel}</span><i />
    </div>
  ) : null;

  if (feed) {
    return (
      <div className={"glm-grid glm-feed" + (loading ? " loading" : "")}>
        {fresh.map(tile)}
        {ruleEl}
        {older.map(tile)}
      </div>
    );
  }
  if (!rule) return grid(items, "all");
  return (
    <>
      {fresh.length ? grid(fresh, "new") : null}
      {ruleEl}
      {older.length ? grid(older, "old") : null}
    </>
  );
}

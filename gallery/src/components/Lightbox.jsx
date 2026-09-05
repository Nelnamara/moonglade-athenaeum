import React, { useCallback, useEffect, useRef, useState } from "react";
import Stars from "./Stars.jsx";
import UpscalePanel from "./UpscalePanel.jsx";
import "../styles/lightbox.css";
import useScrollLock from "../hooks/useScrollLock.js";

/* Full-bleed viewer -- the DC respec (Lightbox.dc.html) over the classic's
   capability set (owner, 2026-07-30: "the current lightbox is full of
   capability we want"): rating with hover-preview, Edit / To Video / Similar /
   Upscale / Details / Slideshow / Close, a filmstrip, the collapsible prompt
   slab, drag/swipe paging, and prev/next that rolls across the pilot's own
   real pagination at either end (classic navigates a real page link; the
   pilot fetches the adjacent page and jumps to its edge item).

   Details is a real link to the app's OWN /?image=<mid> (bookmarkable,
   opens correctly in a new tab/window) -- a plain click intercepts and
   navigates in-app via onOpenDetails; a modifier-key or middle click is left
   alone so the browser's own new-tab/new-window handling still works,
   matching classic's openLightbox(ev, idx) passthrough.

   The stage image/video carries view-transition-name "vt-reveal", paired with
   DetailsView.jsx's placard-frame -- App.jsx's openDetails is what actually
   drives the morph; this element just needs to be nameable when it fires.

   Esc chain (innermost first, per the DC's componentDidMount): the upscale
   flyout swallows every key while open (its scaler control is a native
   <select>, so an open popup is dismissed by the browser itself -- the DC's
   "scaler dropdown first" step); then slideshow/prompt-open cancel; then the
   page-level close back to the gallery. */
export default function Lightbox({
  items, index, setIndex, onClose, onRate, page, pages, loadPage, onEdit, onToVideo,
  onOpenDetails, onPublish, onSimilar,
}) {
  useScrollLock();   // page never scrolls behind a full-screen panel (2026-08-06)
  const it = items[index];
  const mid = it ? it.media_id : null;
  // Warm the neighbors: arrow-nav's cost was a cold /full fetch + decode from zero on
  // every step (part of the owner's "lightbox can load slowly" report, 2026-08-06 —
  // the other, larger part was the IPv6-loopback connect stall, fixed server-side the
  // same day). The browser caches /full/ hard (immutable, 1y), so warming prev/next
  // into that cache makes a step render from memory. Images only — preloading a
  // neighbor VIDEO would pull whole mp4s on every step.
  useEffect(() => {
    for (const n of [items[index - 1], items[index + 1]]) {
      if (n && !n.is_video) { const im = new Image(); im.src = "/full/" + n.media_id; }
    }
  }, [items, index]);
  const [slideOn, setSlideOn] = useState(false);
  const [closing, setClosing] = useState(false);
  const [dragDX, setDragDX] = useState(0);
  const [zoom, setZoom] = useState(false);   // classic's double-tap 2x
  const upEl = useRef(null);
  const closingRef = useRef(false);
  const drag = useRef({ active: false, moved: false });
  const touch = useRef({ x0: 0, dx: 0, live: false, lastTap: 0 });
  const stripRef = useRef(null);

  const closeUpscale = useCallback(() => { if (upEl.current) upEl.current.close(); }, []);
  // "open" for the Esc chain means genuinely open -- a panel 340ms into its own
  // exit fade still reports isOpen(), and re-closing it would only extend the fade.
  const upscaleOpen = () =>
    !!(upEl.current && upEl.current.isOpen() && !upEl.current.isClosing());

  /* Stepping past either end of the CURRENT page rolls to the adjacent page and
     lands on its near edge -- classic's lbStep() does this via a real page nav
     (lbopen=first|last); the pilot already owns pagination client-side, so it
     fetches instead of navigating. Only wraps in place when there's no
     adjacent page, matching classic exactly. */
  const step = useCallback(async (d) => {
    closeUpscale();
    setDragDX(0);
    const ni = index + d;
    if (ni >= 0 && ni < items.length) { setIndex(ni); return; }
    if (d > 0) {
      if (page < pages) { await loadPage(page + 1, true); setIndex(0); }
      else setIndex(0);
    } else {
      // loadPage resolves undefined when a newer request superseded it (App's seq
      // guard) -- a rapid double-← at a page boundary must not throw on .items.
      if (page > 1) { const data = await loadPage(page - 1, true); setIndex(((data && data.items) || []).length - 1); }
      else setIndex(items.length - 1);
    }
  }, [index, items.length, page, pages, loadPage, setIndex, closeUpscale]);

  /* Page-level close plays the exit (overlay law: both directions animate) and
     defers the real unmount 340ms so the lbxOut window has a mounted element.
     Edit/To Video/Similar/Details leave through App's own paths (dock open / the
     gallery's lookalike set / the vt-reveal morph) and are not routed through this. */
  const close = useCallback(() => {
    if (closingRef.current) return;
    closingRef.current = true;
    if (upEl.current) upEl.current.close();
    setSlideOn(false);
    setClosing(true);
    window.setTimeout(onClose, 340);
  }, [onClose]);

  useEffect(() => {
    const onKey = (e) => {
      if (closingRef.current) return;
      if (upscaleOpen()) {
        // Checked BEFORE the input-focus guard on purpose: the panel's own slider/
        // steps/select keep focus after use, and "drag the ratio, hit Esc" must
        // still close the flyout (the DC chain has no focus guard here).
        // innermost layer first: while the upscale flyout is up, Esc closes IT
        // and nothing else fires -- arrows/F stay inert under it (DC exact).
        if (e.key === "Escape") upEl.current.close();
        return;
      }
      if (document.activeElement && /^(input|textarea|select)$/i.test(document.activeElement.tagName)) return;
      if (e.key === "ArrowRight") step(1);
      else if (e.key === "ArrowLeft") step(-1);
      else if (e.key === "f" || e.key === "F") setSlideOn((v) => !v);
      else if (e.key === "Escape") {
        // innermost-first still, with the prompt slab gone: a running slideshow or a
        // double-tap zoom cancels on the first Esc, the page closes on the next.
        if (slideOn || zoom) { setSlideOn(false); setZoom(false); }
        else close();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close, step, slideOn, zoom]);

  /* 4200ms per slide (DC). A timeout keyed on the index, not an interval, so a
     manual step/filmstrip jump restarts the clock -- and the 2px progress bar
     below is keyed the same way, so fill and clock always agree. */
  useEffect(() => {
    if (!slideOn) return;
    const t = setTimeout(() => step(1), 4200);
    return () => clearTimeout(t);
  }, [slideOn, index, step]);

  // Record fields (prompt/negative/loras/seed) belong to Image Details, not here --
  // the viewer no longer calls /api/next/detail at all. Owner, 2026-08-19: the slab was
  // never in the classic lightbox; it arrived via a mis-attribution in this file's own
  // header comment. See design_handoff/.../Lightbox.dc.html (amended in the same pass).

  useEffect(() => { setZoom(false); }, [mid]);   // classic reset zoom on navigate

  // the upscale flyout must never outlive the picture it was opened for
  useEffect(() => { closeUpscale(); }, [mid]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => closeUpscale(), []); // eslint-disable-line react-hooks/exhaustive-deps

  // keep the active filmstrip thumb in view as the index moves
  useEffect(() => {
    const host = stripRef.current;
    if (!host) return;
    const on = host.querySelector(".lbx-thumb.on");
    if (on && on.scrollIntoView) on.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [index]);

  /* Pointer drag AND touch swipe move the image with the finger at 0.35
     parallax, then commit past 90px (mouse) / 70px (touch) -- the tablet
     gesture the old view never had (DC exact). The click that trails a real
     drag is swallowed so it can't fall through to the stage's click-to-close. */
  const startDrag = (e) => {
    if (e.button !== 0) return;
    if (e.target.closest("button, a, video")) return;
    const x0 = e.clientX;
    drag.current = { active: true, moved: false };
    const move = (ev) => {
      const dx = ev.clientX - x0;
      if (Math.abs(dx) > 4) drag.current.moved = true;
      setDragDX(dx);
    };
    const up = (ev) => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      drag.current.active = false;
      const dx = ev.clientX - x0;
      setDragDX(0);
      if (Math.abs(dx) > 90) step(dx < 0 ? 1 : -1);
      setTimeout(() => { drag.current.moved = false; }, 0);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };
  const onTouchStart = (e) => {
    if (e.target.closest("button, a, video")) { touch.current.live = false; return; }
    touch.current = { x0: e.touches[0].clientX, dx: 0, live: true };
  };
  const onTouchMove = (e) => {
    if (!touch.current.live) return;
    const dx = e.touches[0].clientX - touch.current.x0;
    touch.current.dx = dx;
    setDragDX(dx);
  };
  const onTouchEnd = () => {
    if (!touch.current.live) return;
    const dx = touch.current.dx;
    touch.current.live = false;
    setDragDX(0);
    if (Math.abs(dx) > 70) { step(dx < 0 ? 1 : -1); return; }
    // Classic's double-tap-to-zoom, restored (was lost in THE CLASSIC CUT, 579d008):
    // two taps inside 300ms with no meaningful travel toggles a 2x view.
    const now = Date.now();
    if (now - touch.current.lastTap < 300) { setZoom((z) => !z); touch.current.lastTap = 0; }
    else touch.current.lastTap = now;
  };
  // the empty stage around the hero is the backdrop: a clean click there closes
  const stageClick = (e) => {
    if (drag.current.moved) return;
    if (e.target === e.currentTarget) close();
  };

  if (!it) return null;
  const W = parseInt(it.w, 10) || 0;
  const H = parseInt(it.h, 10) || 0;
  const hasAR = W > 0 && H > 0;
  const rating = Number(it.rating) || 0;
  const dragging = dragDX !== 0;

  return (
    <div className={"lbx" + (closing ? " closing" : "")} role="dialog" aria-modal="true">
      {/* the gallery it came from, blurred behind the viewer, under the radial scrim */}
      <div className="lbx-behind" aria-hidden="true">
        {items.slice(0, 18).map((b, i) => (
          <div key={b.media_id || i}
            className={"lbx-btile" + (i % 5 === 0 ? " s2" : "")}
            style={{ backgroundImage: "url('" + b.thumb + "')" }} />
        ))}
      </div>
      <div className="lbx-scrim" aria-hidden="true" />

      <div className="lbx-shell">
        <div className="lbx-bar">
          <div className="lbx-index">
            <b>{index + 1} / {items.length}</b>
            <span>OF {items.length}</span>
          </div>
          <div className="lbx-stars">
            <Stars mediaId={it.media_id} rating={it.rating} onRate={onRate} />
            <span className="lbx-ratelbl">{rating ? rating + " / 5" : "unrated"}</span>
          </div>
          <div className="lbx-meta">
            {it.model ? <span className="lbx-model" title={it.model}>{it.model}</span> : null}
            {it.date ? <span className="lbx-fig">{it.date}</span> : null}
            {hasAR ? <span className="lbx-fig">{W}×{H}</span> : null}
          </div>
          <div className="lbx-acts">
            <button className="lbx-chip" title="Send to the Edit tab"
              onClick={() => onEdit(it.media_id)}>✎ Edit</button>
            <button className="lbx-chip" title="Send as a start frame"
              onClick={() => onToVideo(it.media_id, it.thumb)}>▶ To Video</button>
            {/* ✧ Similar NAVIGATES (Lightbox.dc.html:354 sends it to the gallery): the viewer
                closes and the gallery's own 48-lookalike set opens over the grid -- the same
                destination as Details' "see all". It no longer stacks a modal on the viewer
                ("Where the Refit Broke" #6). */}
            <button className="lbx-chip" title="Lookalikes by eye — the 48 closest"
              onClick={() => onSimilar && onSimilar(it.media_id)}>✧ Similar</button>
            <button className="lbx-chip" title="Upscale or Hires this picture"
              onClick={() => upEl.current && upEl.current.open(it.media_id)}>⇱ Upscale</button>
            {/* ☁ Publish -- the cross-page hand-off (Lightbox.dc.html:357), REAL since
                2026-08-06: it hands this image to the Publish panel, which runs the actual
                createArtworkFromTaskV2 pipeline (preview, then confirm). The DC builds it
                with btn(..., true) -- the PRIMARY/metal treatment, same as Slideshow -- which
                the refit had dropped to a plain chip ("Where the Refit Broke" #6). */}
            <button className="lbx-chip lbx-chip-metal" title="Publish this image to PixAI"
              onClick={() => onPublish && onPublish(it.media_id)}>☁ Publish</button>
            <a className="lbx-chip" title="Open the full record"
              href={"/?image=" + encodeURIComponent(it.media_id)}
              onClick={(e) => {
                if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
                e.preventDefault();
                onOpenDetails(it.media_id);
              }}>
              Details
            </a>
            <button className="lbx-chip lbx-chip-metal" title="F toggles the slideshow"
              onClick={() => setSlideOn((v) => !v)}>
              {slideOn ? "⏸ Pause" : "▶ Slideshow"}
            </button>
            <button className="lbx-chip" title="Esc closes" onClick={close}>✕ Close</button>
          </div>
        </div>

        <div className="lbx-stage" onMouseDown={startDrag}
          onTouchStart={onTouchStart} onTouchMove={onTouchMove} onTouchEnd={onTouchEnd}
          onClick={stageClick}
          style={{ cursor: dragging ? "grabbing" : "grab" }}>
          <button className="lbx-nav lbx-prev" title="Previous — ←" aria-label="Previous"
            onClick={() => step(-1)}>&#8249;</button>
          <button className="lbx-nav lbx-next" title="Next — →" aria-label="Next"
            onClick={() => step(1)}>&#8250;</button>
          <div className="lbx-herowrap" style={{
            transform: "translateX(" + (dragDX * 0.35) + "px)",
            transition: dragging ? "none" : "transform .32s cubic-bezier(.2,.9,.24,1)",
          }}>
            <div className={"lbx-hero" + (hasAR ? "" : " noar")}
              style={hasAR ? {
                aspectRatio: W + " / " + H,
                // the pixel-size cap: never upscale past the file's actual size (lightbox.css)
                "--lbx-w": W + "px", "--lbx-h": H + "px", "--lbx-ar": (W / H).toFixed(5),
              } : undefined}>
              {it.is_video ? (
                <video key={it.media_id} src={"/video-file/" + it.media_id} controls autoPlay loop
                  style={{ viewTransitionName: "vt-reveal" }} />
              ) : (
                <img key={it.media_id} src={"/full/" + it.media_id} alt="" draggable={false}
                  decoding="async" className={zoom ? "zoomed" : ""}
                  style={{ viewTransitionName: "vt-reveal" }} />
              )}
              {slideOn ? (
                <div className="lbx-slidetrack" aria-hidden="true">
                  <div key={page + ":" + index} className="lbx-slidefill" />
                </div>
              ) : null}
            </div>
          </div>
        </div>

        <div className="lbx-bottom">
          <div className="lbx-striprow">
            <div className="lbx-strip" ref={stripRef}>
              {items.map((sh, k) => {
                const sw = parseInt(sh.w, 10) || 0;
                const shh = parseInt(sh.h, 10) || 0;
                const wpx = sw > 0 && shh > 0 ? Math.round(46 * (sw / shh)) : 46;
                return (
                  <button key={sh.media_id} type="button"
                    className={"lbx-thumb" + (k === index ? " on" : "")}
                    style={{ width: wpx + "px" }}
                    title={(k + 1) + " / " + items.length + (sh.model ? " · " + sh.model : "")}
                    onClick={() => { setDragDX(0); setIndex(k); }}>
                    <img src={sh.thumb} alt="" loading="lazy" draggable={false} />
                  </button>
                );
              })}
            </div>
            <div className="lbx-hint">← → to browse · F slideshow · Esc closes · swipe or double-tap on tablet</div>
          </div>
        </div>
      </div>

      {/* flyout mode (no inline): a fixed top-layer modal. The wrapper stops a click inside
          it from reaching the stage's click-to-close; the panel's own scrim closes it. */}
      <div onClick={(e) => e.stopPropagation()}><UpscalePanel ref={upEl} /></div>
    </div>
  );
}

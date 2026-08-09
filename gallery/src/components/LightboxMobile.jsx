import React, { useCallback, useEffect, useRef, useState } from "react";
import Stars from "./Stars.jsx";
import UpscalePanel from "./UpscalePanel.jsx";
import "../styles/lightbox-mobile.css";

/* Lightbox Mobile -- design spec: "Lightbox Mobile.dc.html" (design_handoff_
   moonglade_suite/). The mobile pass of the desktop Lightbox.jsx -- Details'
   own "⛶" full-screen-viewer topbar button (ImageDetailsMobile.jsx) now opens
   THIS instead of the disclosed "coming next" toast it used to show.

   MOUNT / ENTRY POINT: AppMobile.jsx owns `lbIndex` (mirroring desktop
   App.jsx's own lbIndex/Lightbox pairing) and mounts this as a fixed, full-
   viewport overlay -- mutually exclusive with `detailsFor`/ImageDetailsMobile,
   exactly like desktop App.jsx keeps lbIndex/detailsFor mutually exclusive
   (opening one nulls the other). Concretely: Details' ⛶ button resolves its
   media_id to an index into the SAME lib.items array Details/Gallery already
   share and opens this in place of Details; this component's own "Details ›"
   action pill goes the other way, closing itself and opening Details for
   whichever image is currently on screen (may differ from where the user
   started, if they swiped/paged since). Close (X / Esc) only tells the parent
   to null lbIndex -- since Details was already nulled on the way in, that
   lands the user back on the Gallery tab, matching the design file's own real
   cross-file link (close() -> 'Moonglade Mobile.dc.html', the gallery's main
   screen, not back to Details).

   DATA NEEDS -- confirmed by this build's own research pass against the real
   desktop Lightbox.jsx: strictly two tiers, both narrower than
   useImageDetails.js's full detail row (porting that hook wholesale here
   would be a regression, not a simplification -- see that research for the
   full "why not"):
     1. Straight off the shared items array (the same one Gallery/Details
        already read): media_id, thumb, w, h, rating, model, date, prompt,
        is_video -- drives every bit of chrome (index, Stars, meta row, hero,
        filmstrip).
     2. A deliberately LAZY fetch of /api/next/detail/<mid>, only made once the
        prompt slab is actually opened, cached in a plain Map ref (never React
        state) -- and only for NEGATIVE/LORAS, matching the design file's own
        expanded-slab fields exactly (Media ID is it.media_id, already in
        hand, no fetch needed; unlike desktop Lightbox's slab, the design
        shows no Seed row at all -- confirmed dead/unused data in the mock, so
        not surfaced here either).

   GESTURE -- Pointer Events (not touch-only, so a resized desktop browser +
   mouse also drags, matching GalleryGridMobile.jsx's own established
   convention), pointer-captured so a fast drag past the stage's edges keeps
   tracking. Drag-follow transform translateX(dragDX*0.4), commit strictly
   past 60px (the design file's own exact threshold, not desktop Lightbox's
   70/90), snap back under 60px -- both directions ease over .3s cubic-
   bezier(.2,.9,.24,1) once dragDX returns to 0, 0s (no easing lag) while
   actively dragging. Committing a step (drag, chevron, or filmstrip tap) also
   hard-closes the prompt slab, matching the design file's own go() exactly
   (desktop Lightbox does NOT do this -- its animated fold is a separate,
   fancier mechanism this file's own design doesn't call for).

   SLIDESHOW -- same 4200ms-per-slide behavior + progress bar as the design
   file, but built on desktop Lightbox's own proven mechanism (a setTimeout
   keyed on index, restarted by any manual nav, + a CSS keyframe fill keyed
   the same way) rather than reimplementing the design mock's own 120ms
   setInterval poll -- which this build's own research flagged outright as
   "functionally fine for a mock but... the crude mechanism it is." Same
   visible dwell/restart behavior, a real implementation instead of a poll.

   UPSCALE -- the shared React <UpscalePanel inline>, rendered inside this
   component's own bottom-sheet chrome (the same unconditional-render contract
   ImageDetailsMobile.jsx uses -- useImageDetails.js's header, correction 1),
   NOT desktop Lightbox's bare non-inline flyout (position:fixed top-right, the
   wrong shape for a mobile sheet). The Esc-chain below checks the plain
   `sheetOpen` React boolean, not desktop Lightbox's isOpen()/isClosing() nuance
   -- that exists only for the bare-flyout exit-fade timing and doesn't apply to
   this "class toggles a CSS transition" sheet shape.

   (Historical note, 2026-08-08 no-vanilla port: this used to createElement the
   vanilla <mg-upscale-panel> in a `[mid]`-keyed mount effect, keyed on mid --
   not `[]` -- specifically so it would recreate the host div torn down when
   step()'s page-boundary crossing left `index` past a shorter freshly-loaded
   array for one transient `if (!it) return null` render. That whole concern is
   gone: <UpscalePanel> is now plain JSX, so React remounts it automatically the
   moment `it` is valid again -- no mount effect, no host-div-teardown race.)

   EDIT / TO VIDEO / SIMILAR -- the design file's own mock ships these three
   as literal no-op `onClick:()=>{}` stubs. Left as honest, disclosing toasts
   here (this codebase's own established convention for an undone surface --
   see CreateMobile.jsx's Video mode, ImageDetailsMobile.jsx's "Send to
   Video"), not silent dead taps and not newly-invented functionality outside
   this build's brief. Upscale/Details/Slideshow are all real. */

const SLIDE_MS = 4200;

function toast(title, msg) {
  if (window.Toast) window.Toast.show({ title, msg });
}

export default function LightboxMobile({
  items, index, setIndex, onClose, onRate, page, pages, loadPage, onOpenDetails,
}) {
  const it = items[index];
  const mid = it ? it.media_id : null;

  const [closing, setClosing] = useState(false);
  const [slideOn, setSlideOn] = useState(false);
  const [promptOpen, setPromptOpen] = useState(false);
  const [dragDX, setDragDX] = useState(0);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [, bumpDetail] = useState(0); // re-render tick when a lazy detail row lands

  const upEl = useRef(null);
  const closingRef = useRef(false);
  const detailCache = useRef(new Map()); // media_id -> {negative_prompt, loras}
  const dragRef = useRef({ active: false, pointerId: null, x0: 0 });
  const stripRef = useRef(null);

  const closeUpscale = useCallback(() => {
    setSheetOpen(false);
    if (upEl.current) upEl.current.close();
  }, []);
  const toggleUpscale = () => {
    const willOpen = !sheetOpen;
    setSheetOpen(willOpen);
    if (!upEl.current) return;
    if (willOpen) upEl.current.open(it.media_id);
    else upEl.current.close();
  };

  /* Cross-page step -- identical shape to desktop Lightbox.jsx's step(): walk
     within the loaded page directly; past either end, fetch the adjacent
     page and land on its near edge (loadPage's own "replace" resolves the
     fresh page's items synchronously for this). Wraps in place only when
     there's no adjacent page. Also hard-closes the prompt slab and resets
     drag, matching the design file's own go() exactly. */
  const step = useCallback(async (d) => {
    closeUpscale();
    setDragDX(0);
    setPromptOpen(false);
    const ni = index + d;
    if (ni >= 0 && ni < items.length) { setIndex(ni); return; }
    if (d > 0) {
      if (page < pages) { await loadPage(page + 1, true); setIndex(0); }
      else setIndex(0);
    } else {
      if (page > 1) { const data = await loadPage(page - 1, true); setIndex(((data && data.items) || []).length - 1); }
      else setIndex(items.length - 1);
    }
  }, [index, items.length, page, pages, loadPage, setIndex, closeUpscale]);

  const close = useCallback(() => {
    if (closingRef.current) return;
    closingRef.current = true;
    if (upEl.current) upEl.current.close();
    setSlideOn(false);
    setClosing(true);
    window.setTimeout(onClose, 280);
  }, [onClose]);

  // Esc chain (innermost first, matching the design file's own componentDidMount
  // exactly): the upscale sheet swallows Escape alone while open; else arrows
  // step, Escape closes. No F-key -- the design's own key handler never wires
  // one (only its UI buttons toggle slideshow), unlike desktop Lightbox's
  // fuller f/F shortcut.
  useEffect(() => {
    const onKey = (e) => {
      if (closingRef.current) return;
      if (document.activeElement && /^(input|textarea|select)$/i.test(document.activeElement.tagName)) return;
      if (sheetOpen) { if (e.key === "Escape") closeUpscale(); return; }
      if (e.key === "ArrowRight") step(1);
      else if (e.key === "ArrowLeft") step(-1);
      else if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sheetOpen, step, close, closeUpscale]);

  // 4200ms per slide -- a timeout keyed on the index (not an interval), so a
  // manual step/filmstrip jump restarts the clock; the CSS progress bar below
  // is keyed identically so fill and clock always agree.
  useEffect(() => {
    if (!slideOn) return;
    const t = setTimeout(() => step(1), SLIDE_MS);
    return () => clearTimeout(t);
  }, [slideOn, index, step]);

  // The prompt slab's NEGATIVE/LORAS live only on the full detail row
  // (/api/next/detail) -- fetched lazily on first open, cached per media_id.
  // A failed fetch caches {} so the slab settles on em dashes, not a retry loop.
  useEffect(() => {
    if (!mid || !promptOpen || detailCache.current.has(mid)) return;
    let dead = false;
    fetch("/api/next/detail/" + encodeURIComponent(mid))
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        detailCache.current.set(mid, (d && d.row) || {});
        if (!dead) bumpDetail((n) => n + 1);
      })
      .catch(() => {
        detailCache.current.set(mid, {});
        if (!dead) bumpDetail((n) => n + 1);
      });
    return () => { dead = true; };
  }, [mid, promptOpen]);

  // The upscale panel must never outlive the picture it was opened for.
  useEffect(() => { closeUpscale(); }, [mid]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { if (upEl.current) upEl.current.close(); }, []);

  // keep the active filmstrip thumb in view as the index moves
  useEffect(() => {
    const host = stripRef.current;
    if (!host) return;
    const on = host.querySelector(".lbm-thumb.on");
    if (on && on.scrollIntoView) on.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [index]);

  /* Pointer drag -- captured so a fast swipe past the stage's edges keeps
     tracking (Pointer Events, not touch-only, so this also drags with a
     mouse on a resized desktop browser -- GalleryGridMobile.jsx's own
     established convention). Commit strictly past 60px (design exact). */
  const onPointerDown = (e) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    if (e.target.closest("button, a, video")) return;
    dragRef.current = { active: true, pointerId: e.pointerId, x0: e.clientX };
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* unsupported */ }
  };
  const onPointerMove = (e) => {
    const d = dragRef.current;
    if (!d.active || e.pointerId !== d.pointerId) return;
    setDragDX(e.clientX - d.x0);
  };
  const endDrag = (e) => {
    const d = dragRef.current;
    if (!d.active || e.pointerId !== d.pointerId) return;
    d.active = false;
    const dx = e.clientX - d.x0;
    setDragDX(0);
    if (Math.abs(dx) > 60) step(dx < 0 ? 1 : -1);
  };
  const cancelDrag = () => { dragRef.current.active = false; setDragDX(0); };

  if (!it) return null;

  const W = parseInt(it.w, 10) || 0;
  const H = parseInt(it.h, 10) || 0;
  const hasAR = W > 0 && H > 0;
  const dragging = dragDX !== 0;
  const row = detailCache.current.get(mid) || null;
  const pending = promptOpen && !detailCache.current.has(mid);
  const field = (v) => (pending ? "…" : (v == null || v === "" ? "—" : v));
  const promptText = (row && row.prompt_full) || it.prompt || "—";

  return (
    <div className={"lbm-root" + (closing ? " closing" : "")} role="dialog" aria-modal="true" aria-label="Full-screen viewer">
      <div className="lbm-topbar">
        <button type="button" className="lbm-close" onClick={close} aria-label="Close">✕</button>
        <div className="lbm-indexwrap">
          <span className="lbm-index">{index + 1}</span>
          <span className="lbm-total">OF {items.length}</span>
        </div>
        <div className="lbm-starswrap">
          <Stars mediaId={it.media_id} rating={it.rating} onRate={onRate} />
        </div>
        <div className="lbm-fill" />
        <button type="button" className={"lbm-slidebtn" + (slideOn ? " on" : "")}
          onClick={() => setSlideOn((v) => !v)} aria-label="Slideshow" title="Slideshow">
          {slideOn ? "⏸" : "▶"}
        </button>
      </div>

      <div className="lbm-stage"
        onPointerDown={onPointerDown} onPointerMove={onPointerMove}
        onPointerUp={endDrag} onPointerCancel={cancelDrag}>
        <button type="button" className="lbm-nav lbm-prev" aria-label="Previous" onClick={() => step(-1)}>&#8249;</button>
        <button type="button" className="lbm-nav lbm-next" aria-label="Next" onClick={() => step(1)}>&#8250;</button>
        <div className="lbm-herowrap" style={{
          transform: "translateX(" + (dragDX * 0.4) + "px)",
          transition: dragging ? "0s" : "transform .3s cubic-bezier(.2,.9,.24,1)",
        }}>
          <div className={"lbm-hero" + (hasAR ? "" : " noar")} style={hasAR ? { aspectRatio: W + " / " + H } : undefined}>
            {it.is_video ? (
              <video key={it.media_id} src={"/video-file/" + encodeURIComponent(it.media_id)}
                controls autoPlay loop playsInline />
            ) : (
              <img key={it.media_id} src={"/full/" + encodeURIComponent(it.media_id)} alt="" decoding="async" draggable={false} />
            )}
            {slideOn ? (
              <div className="lbm-slidetrack" aria-hidden="true">
                <div key={page + ":" + index} className="lbm-slidefill" />
              </div>
            ) : null}
          </div>
        </div>
      </div>

      <div className="lbm-bottom">
        <div className="lbm-metarow">
          {it.model ? <b className="lbm-model">{it.model}</b> : null}
          {it.date ? <span>{it.date}</span> : null}
          {hasAR ? <span>{W}×{H}</span> : null}
        </div>

        <div className={"lbm-promptbox" + (promptOpen ? " open" : "")}
          onClick={() => setPromptOpen((v) => !v)}>
          <div className="lbm-promptline">
            <span className="lbm-kicker">PROMPT</span>
            <span className={"lbm-prompttext" + (promptOpen ? " full" : "")}>{promptText}</span>
            <span className="lbm-prompttoggle">{promptOpen ? "less" : "more"}</span>
          </div>
          {promptOpen ? (
            <div className="lbm-promptrows">
              <div className="lbm-prow"><span>NEGATIVE</span><i>{field(row && row.negative_prompt)}</i></div>
              <div className="lbm-prow"><span>LORAS</span><i>{field(row && row.loras)}</i></div>
              <div className="lbm-prow"><span>MEDIA ID</span><i className="mono">{it.media_id}</i></div>
            </div>
          ) : null}
        </div>

        <div className="lbm-strip" ref={stripRef}>
          {items.map((sh, k) => {
            const sw = parseInt(sh.w, 10) || 0;
            const shh = parseInt(sh.h, 10) || 0;
            const wpx = sw > 0 && shh > 0 ? Math.round(44 * (sw / shh)) : 44;
            return (
              <button key={sh.media_id} type="button" className={"lbm-thumb" + (k === index ? " on" : "")}
                style={{ width: wpx + "px" }}
                title={(k + 1) + " / " + items.length}
                onClick={() => { setDragDX(0); setPromptOpen(false); setIndex(k); }}>
                <img src={sh.thumb} alt="" loading="lazy" draggable={false} />
              </button>
            );
          })}
        </div>

        <div className="lbm-actsrow">
          <button type="button" className="lbm-chip"
            onClick={() => toast("Edit", "Its own mobile wiring — coming later.")}>✎ Edit</button>
          <button type="button" className="lbm-chip"
            onClick={() => toast("Send to Video", "Its own mobile wiring — coming later.")}>▶ To Video</button>
          <button type="button" className="lbm-chip"
            onClick={() => toast("Similar", "Its own mobile pass — coming later.")}>✧ Similar</button>
          <button type="button" className={"lbm-chip" + (sheetOpen ? " on" : "")} onClick={toggleUpscale}>⇱ Upscale</button>
          <button type="button" className="lbm-chip" onClick={() => onOpenDetails(it.media_id)}>Details ›</button>
          <button type="button" className="lbm-chip lbm-chip-metal" onClick={() => setSlideOn((v) => !v)}>
            {slideOn ? "⏸ Pause" : "▶ Slideshow"}
          </button>
        </div>
        <div className="lbm-hint">‹ › to browse · swipe the photo · ▶ for slideshow</div>
      </div>

      <div className={"lbm-sheet-scrim" + (sheetOpen ? " open" : "")} onClick={toggleUpscale} aria-hidden={!sheetOpen} />
      <div className={"lbm-sheet-slab" + (sheetOpen ? " open" : "")} role="dialog" aria-modal={sheetOpen} aria-label="Upscale">
        <div className="lbm-sheet-head">
          <span className="lbm-sheet-title">⇱ Upscale</span>
          <button type="button" className="lbm-sheet-x" onClick={toggleUpscale} aria-label="Close">×</button>
        </div>
        <UpscalePanel ref={upEl} inline />
      </div>
    </div>
  );
}

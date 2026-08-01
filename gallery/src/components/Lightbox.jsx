import React, { useCallback, useEffect, useRef, useState } from "react";
import Stars from "./Stars.jsx";
import SimilarModal from "./SimilarModal.jsx";

/* Full-res overlay -- classic's lightbox capability set (owner, 2026-07-30: "the
   current lightbox is full of capability we want"), ported: rating, Edit / To
   Video / Similar / Upscale / Details / Slideshow / Close, prev/next that rolls
   across the pilot's own real pagination at either end (classic navigates a real
   page link; the pilot fetches the adjacent page and jumps to its edge item).

   Details is a real link to the pilot's OWN /next?image=<mid> (bookmarkable,
   opens correctly in a new tab/window) -- a plain click intercepts and
   navigates in-app via onOpenDetails; a modifier-key or middle click is left
   alone so the browser's own new-tab/new-window handling still works,
   matching classic's openLightbox(ev, idx) passthrough.

   The stage image/video carries view-transition-name "vt-reveal", paired with
   DetailsView.jsx's placard-frame -- App.jsx's openDetails is what actually
   drives the morph; this element just needs to be nameable when it fires. */
export default function Lightbox({
  items, index, setIndex, onClose, onRate, page, pages, loadPage, onEdit, onToVideo,
  onOpenDetails,
}) {
  const it = items[index];
  const [similarFor, setSimilarFor] = useState(null);
  const [slideOn, setSlideOn] = useState(false);
  const upHost = useRef(null);
  const upEl = useRef(null);
  const slideTimer = useRef(null);

  useEffect(() => {
    if (!upHost.current || upHost.current.firstChild) return;
    if (!window.customElements || !window.customElements.get("mg-upscale-panel")) return;
    const el = document.createElement("mg-upscale-panel");
    upHost.current.appendChild(el);
    upEl.current = el;
  }, []);

  const closeUpscale = useCallback(() => { if (upEl.current) upEl.current.close(); }, []);

  /* Stepping past either end of the CURRENT page rolls to the adjacent page and
     lands on its near edge -- classic's lbStep() does this via a real page nav
     (lbopen=first|last); the pilot already owns pagination client-side, so it
     fetches instead of navigating. Only wraps in place when there's no
     adjacent page, matching classic exactly. */
  const step = useCallback(async (d) => {
    closeUpscale();
    const ni = index + d;
    if (ni >= 0 && ni < items.length) { setIndex(ni); return; }
    if (d > 0) {
      if (page < pages) { await loadPage(page + 1, true); setIndex(0); }
      else setIndex(0);
    } else {
      if (page > 1) { const data = await loadPage(page - 1, true); setIndex((data.items || []).length - 1); }
      else setIndex(items.length - 1);
    }
  }, [index, items.length, page, pages, loadPage, setIndex, closeUpscale]);

  const close = useCallback(() => {
    closeUpscale();
    setSlideOn(false);
    onClose();
  }, [closeUpscale, onClose]);

  useEffect(() => {
    const onKey = (e) => {
      if (document.activeElement && /^(input|textarea)$/i.test(document.activeElement.tagName)) return;
      if (e.key === "Escape") close();
      else if (e.key === "ArrowRight") step(1);
      else if (e.key === "ArrowLeft") step(-1);
      else if (e.key === "f" || e.key === "F") setSlideOn((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close, step]);

  useEffect(() => {
    if (!slideOn) return;
    slideTimer.current = setInterval(() => step(1), 3000);
    return () => clearInterval(slideTimer.current);
  }, [slideOn, step]);

  // the upscale flyout must never outlive the picture it was opened for
  useEffect(() => { closeUpscale(); }, [it && it.media_id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => closeUpscale(), []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!it) return null;
  return (
    <div className="lb" onClick={close} role="dialog" aria-modal="true">
      <div className="lbinner" onClick={(e) => e.stopPropagation()}>
        <div className="lbbar">
          <span className="lbcap">{index + 1} / {items.length}</span>
          <Stars mediaId={it.media_id} rating={it.rating} onRate={onRate} />
          {it.model ? <span className="dim">{it.model}</span> : null}
          {it.date ? <span className="dim">{it.date}</span> : null}
          {it.w && it.h ? <span className="dim">{it.w}×{it.h}</span> : null}
          <span className="sp" />
          <div className="lbacts">
            <button onClick={() => onEdit(it.media_id)} title="Open in the Edit tab">✎ Edit</button>
            <button onClick={() => onToVideo(it.media_id, it.thumb)} title="Send to the Video tab as a reference">▶ To Video</button>
            <button onClick={() => setSimilarFor(it.media_id)} title="Find visually similar images">✧ Similar</button>
            <button onClick={() => upEl.current && upEl.current.open(it.media_id)} title="Upscale this image (PixAI Upscale or Hires)">⇱ Upscale</button>
            <a className="lbact" href={"/next?image=" + encodeURIComponent(it.media_id)}
              onClick={(e) => {
                if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
                e.preventDefault();
                onOpenDetails(it.media_id);
              }}>
              Details
            </a>
            <button onClick={() => setSlideOn((v) => !v)}>{slideOn ? "❚❚ Pause" : "▶ Slideshow"}</button>
            <button onClick={close} title="Esc">✕ Close</button>
          </div>
        </div>
        <div className="lbstage">
          <button className="lbnav lbprev" onClick={() => step(-1)} aria-label="Previous">&#8249;</button>
          {it.is_video ? (
            <video key={it.media_id} src={"/video-file/" + it.media_id} controls autoPlay loop
              style={{ viewTransitionName: "vt-reveal" }} />
          ) : (
            <img key={it.media_id} src={"/full/" + it.media_id} alt=""
              style={{ viewTransitionName: "vt-reveal" }} />
          )}
          <button className="lbnav lbnext" onClick={() => step(1)} aria-label="Next">&#8250;</button>
        </div>
        {it.prompt ? <div className="lbprompt">{it.prompt}</div> : null}
      </div>
      <div ref={upHost} onClick={(e) => e.stopPropagation()} />
      <SimilarModal mediaId={similarFor} onClose={() => setSimilarFor(null)} onOpenDetails={onOpenDetails} />
    </div>
  );
}

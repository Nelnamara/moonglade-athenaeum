import React, { useEffect, useRef, useState } from "react";
import { apiGet } from "../api.js";

/* "More like this" -- classic's Similar object (moonglade_gallery.py's shared
   INDEX_HTML script), ported to a component. GET /api/similar/<mid>?k=48 runs
   a CLIP nearest-neighbor lookup over the local catalog (moonglade_similar.py);
   fails soft to an empty list if that sidecar index isn't built yet, and the
   route distinguishes a genuinely-empty index from a real zero-match result.

   Each result links to the app's own Details view (/?image=<mid>,
   bookmarkable), same modifier-key passthrough as the lightbox's own Details
   link: a plain click intercepts and navigates in-app, ctrl/cmd/middle-click
   is left alone for the browser's own new-tab handling. */
export default function SimilarModal({ mediaId, onClose, onOpenDetails }) {
  const [state, setState] = useState({ loading: true, images: [], error: "" });
  const seq = useRef(0);

  useEffect(() => {
    if (!mediaId) return;
    const mine = ++seq.current;
    setState({ loading: true, images: [], error: "" });
    apiGet("/api/similar/" + encodeURIComponent(mediaId) + "?k=48")
      .then((d) => {
        if (mine !== seq.current) return;
        const images = (d && d.images) || [];
        setState({
          loading: false, images,
          error: images.length ? "" : ((d && d.error) || "No similar images found for this one."),
        });
      })
      .catch(() => {
        if (mine !== seq.current) return;
        setState({ loading: false, images: [], error: "Could not load similar images." });
      });
  }, [mediaId]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Every handler here stops propagation: this modal is rendered as a CHILD of
  // the lightbox's own backdrop (that div's onClick closes the whole lightbox
  // on any click reaching it), so an unstopped click bubbling up from the
  // scrim or the × button closed the lightbox too, not just this modal
  // (caught live: closing Similar took the whole lightbox with it).
  const stop = (fn) => (e) => { e.stopPropagation(); fn(); };

  if (!mediaId) return null;
  return (
    <>
      <div className="similar-scrim open" onClick={stop(onClose)} />
      <div className="similar-modal open" aria-label="Visually similar images" onClick={(e) => e.stopPropagation()}>
        <div className="pick-head">
          <span className="t">✧ Visually similar</span>
          <button className="x" onClick={stop(onClose)} aria-label="Close">&times;</button>
        </div>
        {state.loading ? (
          <div className="pick-empty">Finding lookalikes…</div>
        ) : state.images.length ? (
          <div className="similar-grid">
            {state.images.map((it) => (
              <a key={it.media_id} className="scard"
                href={"/?image=" + encodeURIComponent(it.media_id)}
                onClick={(e) => {
                  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
                  e.preventDefault();
                  e.stopPropagation();
                  onClose();
                  onOpenDetails(it.media_id);
                }}>
                <img src={it.thumb} loading="lazy" decoding="async" alt="" />
                {it.is_video === "1" ? <div className="vbadge" title="Video">▶</div> : null}
                <div className="smeta">✧ {it.score != null ? it.score : ""}</div>
              </a>
            ))}
          </div>
        ) : (
          <div className="pick-empty">{state.error}</div>
        )}
      </div>
    </>
  );
}

import { useEffect, useRef, useState } from "react";
import { apiGet } from "../api.js";

/* "More like this" -- the one data path behind every Similar surface (the Details
   record's inline strip on desktop AND mobile, and the gallery's 48-grid modal):
   GET /api/similar/<mid>?k=48, a CLIP nearest-neighbour lookup over the local
   catalog (moonglade_similar.py). The route is the availability gate, and it fails
   soft: no ML stack / no sidecar index / an EMPTY index / no hits all come back as
   `images: []` plus an `error` line (200, never a 500) -- so a caller that wants to
   hide rather than explain simply renders nothing when `images` is empty.

   Lifted verbatim from ImageDetailsMobile.jsx (where it was born) so DetailsView.jsx
   can share it without importing the mobile component. The seq
   guard drops a stale response when the media id changes mid-flight. */
export default function useSimilar(mediaId) {
  const [state, setState] = useState({ loading: true, images: [], error: "" });
  const seq = useRef(0);

  useEffect(() => {
    if (!mediaId) { setState({ loading: false, images: [], error: "" }); return; }
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
        if (mine === seq.current) setState({ loading: false, images: [], error: "Could not load similar images." });
      });
  }, [mediaId]);

  return state;
}

import React from "react";

/* Clickable 5-star rating -- classic's exact semantics (same star clears),
   POSTs through App.jsx's optimistic rate() to /rate/<media_id>. Shared by the
   grid card, the lightbox and the details view: one control, three mounts. */
export default function Stars({ mediaId, rating, onRate, big }) {
  const val = Number(rating) || 0;
  return (
    <span className={"stars" + (big ? " big" : "")} aria-label={"rating " + val}>
      {[1, 2, 3, 4, 5].map((k) => (
        <button key={k} type="button" className={"st" + (k <= val ? " lit" : "")}
          title={"Rate " + k + (k === val ? " (click again to clear)" : "")}
          onClick={(e) => {
            e.stopPropagation();
            onRate(mediaId, k === val ? 0 : k);
          }}>
          ★
        </button>
      ))}
    </span>
  );
}

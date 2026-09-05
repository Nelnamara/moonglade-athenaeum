import React from "react";
import "../styles/similar.css";

/* ============================================================================
   B2 -- "Similar", one system (Gallery Chrome Handoff.dc.html, 2026-09-04).

   WHAT CHANGED. This file was SimilarModal.jsx: a fixed, scrimmed modal that
   floated over the gallery, owned its own fetch and its own Escape key, and had
   to be dismissed with its own ×. The handoff replaces that with one state on
   the library itself -- the ◈ token in the search bar says what you are looking
   at, and the results simply take the grid's place underneath it. So this is a
   plain in-flow surface now: no scrim, no position:fixed, no key handling, no
   fetching. App.jsx owns the media id (`similarFor`), the fetch (useSimilar) and
   the Escape ladder; this renders what it is handed.

   The data path is unchanged and deliberately so: GET /api/similar/<mid>?k=48,
   the CLIP nearest-neighbour lookup over the local catalog (moonglade_similar.py),
   read through hooks/useSimilar.js -- the same one call the Details record's
   inline strip has always used. Every ◈ door in the app lands here, so there is
   exactly one similarity code path and one result surface.

   The route fails SOFT: no ML stack, no sidecar index, an empty index, or no
   hits all return `images: []` plus an `error` line (200, never a 500). Because
   the results now occupy the grid rather than a modal that could just decline to
   open, an empty answer must say something -- so the error line is rendered
   rather than swallowed, with the token still up and dismissible.

   Result tiles link to the app's own Details view (/?image=<mid>, bookmarkable)
   with the same modifier-key passthrough the lightbox's Details link uses: a
   plain click navigates in-app, ctrl/cmd/shift/middle-click is left to the
   browser's own new-tab handling.
   ========================================================================== */
export default function SimilarResults({ source, state, onOpenDetails, onSimilar, onClear }) {
  const { loading, images, error } = state;

  // The source picture leads the set, badged, so the answer to "similar to WHAT?"
  // is on screen and not only in the token up in the bar (handoff: the first tile
  // wears a `source` mark and the lavender ring).
  const sourceTile = source ? (
    <div className="simres-card is-source" title="The picture these are compared against">
      <img src={source.thumb} alt="" loading="lazy" decoding="async" />
      <span className="simres-mark">source</span>
    </div>
  ) : null;

  return (
    <div className="simres" aria-label="Visually similar images">
      {loading ? (
        <div className="simres-note">Finding lookalikes…</div>
      ) : images.length ? (
        <div className="simres-grid">
          {sourceTile}
          {images.map((it) => (
            <a
              key={it.media_id}
              className="simres-card"
              href={"/?image=" + encodeURIComponent(it.media_id)}
              onClick={(e) => {
                if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
                e.preventDefault();
                onOpenDetails(it.media_id);
              }}
            >
              <img src={it.thumb} alt="" loading="lazy" decoding="async" />
              {it.is_video === "1" ? <span className="simres-vbadge" title="Video">▶</span> : null}
              {/* The ◈ door rides every result too: one click re-anchors the same
                  view on THIS picture, which is how a search by eye is actually
                  walked. Same mark, same verb, same token -- it just re-points. */}
              {onSimilar ? (
                <button
                  type="button" className="simres-door" title="Find what looks like this one"
                  aria-label="Find what looks like this one"
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); onSimilar(it.media_id); }}
                >◈</button>
              ) : null}
              {it.score != null ? <span className="simres-score">◈ {it.score}</span> : null}
            </a>
          ))}
        </div>
      ) : (
        <div className="simres-empty">
          {/* The route's own words: "the index is empty, rebuild it from the Control
              Panel", "similarity index unavailable: …", or a plain no-hits line. It
              knows which of those is true; repeating a guess here would be the exact
              conflation the route was fixed to stop making. */}
          <p className="simres-note">{error || "No similar images found for this one."}</p>
          <button type="button" className="simres-back" onClick={onClear}>← Back to the library</button>
        </div>
      )}
    </div>
  );
}

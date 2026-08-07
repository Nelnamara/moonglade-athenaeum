import React from "react";
import { createPortal } from "react-dom";
import useContactSheet, { pad } from "../hooks/useContactSheet.js";
import "../styles/overlays.css";
import "../styles/contact-sheet-overlay.css";
import useScrollLock from "../hooks/useScrollLock.js";

/* Contact Sheet overlay — a native React build, not a hand-off to the classic
   /contact-sheet page (that route stays, untouched, for classic's own use
   until demolition; the new front door never opens it). Data comes from the
   JSON twin GET /api/contact-sheet (moonglade_gallery.py, reuses the same
   rows_for_media_ids / query_catalog / rating->stars logic the page route
   already proved). The on-screen layout follows the DC's Contact
   Sheet.dc.html; the print output is genuinely native — window.print()
   scoped by the @media print rule in contact-sheet-overlay.css, so what
   prints is the live React DOM, not a server-rendered document.

   Fetch/state logic lifted out to useContactSheet.js (2026-08-03), the same
   precedent useFolio.js/useHealth.js/useImageDetails.js/useControlPanel.js
   already set this session -- this component (the ONE place the fetch used
   to live) is refactored to CONSUME the hook rather than hold a second copy,
   and the new mobile screen (ContactSheetMobile.jsx) consumes the identical
   hook instance-per-mount. See useContactSheet.js's own header comment.

   Portaled straight to document.body (NOT rendered inline in App's tree,
   unlike every other overlay). Caught live: nested inline, this sits deep
   inside #root AFTER the full gallery grid in DOM order. visibility:hidden
   hides paint but not LAYOUT HEIGHT, so print pagination reflected the
   entire hidden grid's real height (thousands of px, 2000+ images) with the
   actual sheet content buried many pages down -- rendered as ~8 solid dark
   blank pages, none of which happened to be the one shown in preview. A
   portal lets print CSS just hide #root outright (display:none, zero
   height) and print this sibling's own natural (small) height instead. */

export default function ContactSheetOverlay({ ids, collectionName, onClose }) {
  useScrollLock();   // page never scrolls behind a full-screen panel (2026-08-06)
  const { data, err } = useContactSheet({ ids, collectionName });

  return createPortal(
    <>
      <div className="mgv-scrim" onClick={onClose} />
      <div className="mgv-host">
        <div className="mgv-slab mgcs-slab" role="dialog" aria-label="Contact Sheet">
          <div className="mgv-titlerow">
            <div className="mgv-title">Contact Sheet</div>
            <button type="button" className="mgcs-print" disabled={!data}
              title="Print this sheet" onClick={() => window.print()}>
              🖶 Print
            </button>
            <button type="button" className="mgv-x" onClick={onClose} aria-label="Close">×</button>
          </div>

          {!data && !err && <div className="mgh-loading">building the sheet…</div>}
          {err && <div className="mgh-loading">couldn't load the sheet — {err}</div>}

          {data && (
            <div className="mgcs-print-area">
              <div className="mgcs-header">
                <div className="mgcs-eyebrow">Moonglade Athenaeum</div>
                <div className="mgcs-headrow">
                  <div className="mgcs-label">Contact Sheet — {data.collectionName}</div>
                  <div className="mgcs-meta">{data.frameCount} frames · printed {data.printedDate}</div>
                </div>
                <div className="mgcs-rule" />
              </div>
              <h1 className="mgcs-h1">Contact Sheet</h1>
              <div className="mgcs-sub">
                {data.collectionName}
                {/* the "N selected" collection name already carries the count for an
                    explicit-ids sheet -- repeating "N selects" right after it reads
                    as a stutter, so only add it when the name doesn't already say so */}
                {!/\bselected$/i.test(data.collectionName) &&
                  " · " + data.frameCount + " select" + (data.frameCount === 1 ? "" : "s")}
                {" · printed " + data.printedDate}
              </div>

              {data.frames.length === 0 ? (
                <div className="mgcs-empty">Nothing to print — the selection is empty.</div>
              ) : (
                <div className="mgcs-grid">
                  {data.frames.map((f, i) => (
                    <div className="mgcs-cell" key={f.media_id}>
                      <div className="mgcs-img">
                        {/* NOT loading="lazy": this whole component exists to be
                            printed as one document. A lazy image that never
                            scrolled into view before Print is clicked never
                            fetches its src -- it prints blank. Caught live: a
                            20-frame sheet printed as ~8 near-empty dark pages
                            because only the first couple rows had ever been
                            scrolled past on screen. */}
                        <img src={f.thumb_url} alt="" />
                      </div>
                      <div className="mgcs-no">No. {pad(i + 1, 3)}</div>
                      <div className="mgcs-cap-title" title={f.title}>{f.title}</div>
                      <div className="mgcs-cap-sub">
                        {f.model}{f.model && f.stars ? " · " : ""}{f.stars}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </>,
    document.body
  );
}

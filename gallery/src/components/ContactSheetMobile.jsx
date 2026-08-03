import React, { useState } from "react";
import useContactSheet, { pad } from "../hooks/useContactSheet.js";
import "../styles/gallery-mobile.css";
import "../styles/contact-sheet-mobile.css";

/* Contact Sheet Mobile -- design spec: "Contact Sheet Mobile.dc.html" (design_
   handoff_moonglade_suite/). Data comes from useContactSheet.js -- the EXACT
   same GET /api/contact-sheet fetch ContactSheetOverlay.jsx (desktop)
   consumes (itself refactored to CONSUME that hook this same pass, see its
   own header comment) -- one fetch, one ids-or-collection selection
   contract, never a second copy of it.

   ENTRY POINT: the Gallery tab's Actions sheet (GalleryMobile.jsx mounts
   ActionsMenu.jsx "as-is", per this session's own established precedent --
   see GalleryMobile.jsx's own header comment) already has a real "▤ Print
   sheet" item; it previously fell through to ActionsMenu's own desktop-shaped
   fallback (window.open("/contact-sheet?ids=...", "_blank") -- the classic
   print page in a bare new tab, no real mobile destination). GalleryMobile
   now passes `onPrintSheet`, which closes the Actions sheet and calls
   AppMobile.jsx's lifted `openContactSheet(selIds)` in the same click --
   mirroring desktop App.jsx's own `printSheet: () => openContactSheet(selIds)`
   exactly. `contactSheetTarget`/openContactSheet/closeContactSheet are lifted
   to AppMobile.jsx for the identical reason detailsFor/lbIndex/folioOpen are
   (see AppMobile.jsx's own header comment): reachable from the Gallery tab,
   must cover the WHOLE app shell, so this renders as a fixed overlay sibling
   of ImageDetailsMobile/LightboxMobile/FolioMobile, not nested in any one
   tab's own content. Desktop's SECOND entry point (the Advanced flyout's
   "printCollection", printing the current collection view rather than an
   explicit selection) has no mobile equivalent anywhere yet -- out of scope
   for this pass, not an oversight; the hook/component both already accept a
   `collectionName` target so wiring a second mobile entry point later is a
   pure addition, not a rework.

   WHY A DEDICATED FULL-SCREEN PRESENTATION, NOT MobileScreen.jsx: same
   reasoning as ImageDetailsMobile.jsx/FolioMobile.jsx's own header comments
   -- the design's own top bar carries BOTH a Back link and a Share action,
   a two-affordance header MobileScreen's fixed single back-chevron contract
   wasn't built for.

   LAYOUT, per the design and the drift-report's own "Mobile Contact Sheet"
   note (drift-report.md item 26, 2026-08-03) -- disclosed real-app-truth
   deviations from the mock, same disclosure standard every prior mobile
   surface this session used:
     1. SINGLE-COLUMN SCROLLABLE LIST, not desktop's 4-across print grid --
        the design's own layout, not a scaled-down copy of contact-sheet-
        overlay.css's .mgcs-grid.
     2. PLACEHOLDER-QUALITY THUMBNAILS, real per-image content NOT loaded --
        locked by the drift report ("no per-image browse" -- this screen is
        for browsing/sharing the LIST, not inspecting each frame), so every
        card renders the design's own decorative gradient box rather than a
        real /thumbs/<id>.jpg, even though useContactSheet's data.frames[]
        carries a real thumb_url for each one. Not a missing-data gap --
        deliberately unused data, see contact-sheet-mobile.css's own comment
        on .csm-thumb.
     3. SHARE, NOT PRINT -- the design mock's own onShare is a bare
        alert('Share Contact Sheet (or export as PDF)') stub; the real
        behavior (drift report: "Share button routes OS-native print/export
        -- window.print() unreliable on iOS/Android") is the Web Share API
        (navigator.share) handed a real link to the classic, already-shipped
        `/contact-sheet` print page (GET, server-rendered, real thumbnails,
        real @page print CSS) carrying the SAME ids/collection this sheet
        fetched -- so whatever the OS share sheet hands off to (Mail,
        Messages, "Print" from Safari's own share sheet, "Save to Files" as
        a PDF, another device) opens a page that actually prints correctly,
        rather than trying to drive window.print() against this screen's own
        placeholder-thumbnail DOM. Browsers with no navigator.share (older
        Android WebViews, some desktop test surfaces) fall back to opening
        that same URL in a new tab, so the action is never a dead end. */

export default function ContactSheetMobile({ ids, collectionName, onClose }) {
  const [closing, setClosing] = useState(false);
  const { data, err, shareUrl } = useContactSheet({ ids, collectionName });

  const close = () => {
    setClosing(true);
    setTimeout(onClose, 200);
  };

  const onShare = async () => {
    if (!data) return;
    const url = window.location.origin + shareUrl;
    const title = "Contact Sheet — " + data.collectionName;
    if (navigator.share) {
      try {
        await navigator.share({ title, url });
      } catch (e) {
        // AbortError = the user dismissed the OS share sheet themselves --
        // not a real failure, nothing to surface.
        if (e && e.name !== "AbortError" && window.Toast) {
          window.Toast.show({ kind: "err", title: "Couldn't share", msg: String((e && e.message) || e) });
        }
      }
      return;
    }
    // No Web Share API on this browser: open the same print-ready page
    // directly so its own share/print/Save-as-PDF affordances stay reachable.
    window.open(url, "_blank");
  };

  return (
    <div className={"csm-root" + (closing ? " closing" : "")} role="dialog" aria-modal="true"
      aria-label="Contact Sheet">
      <div className="csm-topbar">
        <button type="button" className="csm-back" onClick={close}>← Back</button>
        <div className="csm-fill" />
        <button type="button" className="csm-share" disabled={!data} onClick={onShare}>Share</button>
      </div>

      <div className="csm-titleblock">
        <div className="csm-title">Contact Sheet</div>
        <div className="csm-meta">
          {data
            ? data.collectionName + " · " + data.frameCount + " frame" + (data.frameCount === 1 ? "" : "s") +
              " · " + data.printedDate
            : "loading…"}
        </div>
      </div>

      <div className="csm-body">
        {!data && !err && <div className="csm-loading">building the sheet…</div>}
        {err && <div className="csm-loading">couldn't load the sheet — {err}</div>}
        {data && data.frames.length === 0 && (
          <div className="csm-empty">Nothing to share — the selection is empty.</div>
        )}
        {data && data.frames.length > 0 && (
          <div className="csm-list">
            {data.frames.map((f, i) => (
              <div className="csm-card" key={f.media_id}>
                <div className="csm-thumb" aria-hidden="true" />
                <div className="csm-info">
                  <div className="csm-row1">
                    <span className="csm-no">No. {pad(i + 1, 3)}</span>
                    <span className="csm-cardtitle" title={f.title}>{f.title}</span>
                  </div>
                  <div className="csm-model">{f.model}</div>
                  <div className="csm-stars">{f.stars}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

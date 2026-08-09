import React, { useRef } from "react";
import useImport from "../hooks/useImport.js";
import "../styles/import-overlay.css";
import "../styles/gallery-mobile.css";
import "../styles/create-mobile.css";

/* Import -- mobile screen (design spec: Moonglade Mobile.dc.html
   screenIsImport block, lines 576-585). Pushed via MobileScreen.jsx from
   AppMobile.jsx's Menu sheet, replacing that destination's former honest
   placeholder. Data layer: useImport.js, the EXACT hook ImportOverlay.jsx
   (desktop) now consumes too -- same POST /api/import-local, same de-dupe/
   media-only filter/24-file preview cap, same result.ok-checked-before-
   files.length===0 render order that fixes the "the server logged a real
   import, the UI never showed it" bug ImportOverlay.jsx's own header
   comment documents -- ported via the shared hook, not re-derived.

   THE ONE THING THE DESIGN NEVER SPECIFIES (its own header note, confirmed
   by grep -- no <input type="file">, no webkitdirectory, no drag handler
   anywhere in that section of the mock): how files get INTO this screen on
   a phone. Built off classic's real picker, adapted for touch:
   1. ONE "Browse files…" button (a real, hidden <input type="file" multiple
      accept="image/*,video/*,.zip">) -- desktop's SECOND button, "Browse a
      folder…" (webkitdirectory), is dropped here: no design guidance exists
      for it, and webkitdirectory has no reliable mobile-browser support to
      build a real affordance around (iOS Safari doesn't implement it at
      all) -- a disclosed scope decision, not an oversight.
   2. No drag-and-drop zone -- there's no drag source on a touchscreen, so
      desktop's dragActive/onDrag* handlers (still in useImport.js, for
      ImportOverlay.jsx's benefit) are simply never wired here.

   COLLECTION PICKER: the design shows a plain <select> (not desktop's
   custom dropdown-with-inline-new-collection-input). This uses a real
   <select> of the live `collections` prop (the SAME data ImportOverlay.jsx's
   own picker reads) plus a conditional text input for "+ New collection…"
   -- the shape the design asks for, with the FULL real capability desktop
   has (new-collection-on-the-fly), not a trimmed-down copy of it.

   ACTIONS: the design shows ONE button ("↑ Import N files"), no Cancel and
   no post-import "Done" -- because MobileScreen.jsx's own back-chevron
   already IS Cancel/Done here (unlike desktop's modal, which has no other
   way out). Kept "Import more" (clears the done state without leaving the
   screen -- the one action the chevron alone can't do). */

export default function ImportMobile({ collections, onImported }) {
  const {
    files, collection, setCollection, newCollName, setNewCollName,
    busy, result, setResult, addFiles, removeFile, counts, summary, thumbUrl, doImport,
    previewCapped, previewList, CAP, kindOf, fmtSize, NEW_COLL,
  } = useImport({ onImported });
  const fileInputRef = useRef(null);

  return (
    <>
      <div className="mgim-note">
        Bring local files into the catalog — copied into <b>imported/</b> and tagged{" "}
        <b>Imported (local)</b>. Nothing is uploaded to PixAI; this is your library, not a
        generation reference.
      </div>

      <input ref={fileInputRef} type="file" multiple accept="image/*,video/*,.zip" style={{ display: "none" }}
        onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />

      {result && result.ok ? (
        /* Same fix ImportOverlay.jsx's own header comment documents: `files`
           is already cleared on success, so this branch must be checked
           BEFORE files.length===0 or the confirmation never renders. */
        <div className="mgim-done">
          <div className="mgim-result ok">
            ✓ Imported <b>{result.imported}</b> file{result.imported !== 1 ? "s" : ""}
            {result.skipped ? " · " + result.skipped + " skipped (already in library)" : ""}
            {result.collection ? " · added to “" + result.collection + "”" : ""}.
          </div>
          <div className="glm-sheet-actions" style={{ marginTop: 10 }}>
            <button type="button" className="glm-metal glm-widebtn" onClick={() => setResult(null)}>Import more</button>
          </div>
        </div>
      ) : files.length === 0 ? (
        <div className="mgim-drop">
          <div className="mgim-drop-icon">⬆</div>
          <div className="mgim-drop-text">Pick images, videos, or a .zip from your device</div>
          <div className="mgim-drop-buttons">
            <button type="button" className="mgim-btn" onClick={() => fileInputRef.current?.click()}>Browse files…</button>
          </div>
        </div>
      ) : (
        <>
          <div className="mgim-summary">
            <b>{files.length} file{files.length !== 1 ? "s" : ""}</b> · {summary} · {fmtSize(counts.bytes)}
          </div>

          {previewCapped && (
            <div className="mgim-cap">
              ⓘ Preview capped at {CAP} — <b>all {files.length} will import</b> (only the preview is capped).
            </div>
          )}
          <div className={previewCapped ? "mgim-grid" : "mgim-rows"}>
            {previewList.map((f, i) => {
              const url = thumbUrl(f);
              return previewCapped ? (
                <div className="mgim-tile" key={f.name + f.size}>
                  {url ? <img src={url} alt="" /> : <span>{kindOf(f) === "video" ? "▶" : "📦"}</span>}
                </div>
              ) : (
                <div className="mgim-row" key={f.name + f.size}>
                  <span className="mgim-thumb">
                    {url ? <img src={url} alt="" /> : <span>{kindOf(f) === "video" ? "▶" : "📦"}</span>}
                  </span>
                  <span className="mgim-nm" title={f.name}>{f.name}</span>
                  <span className="mgim-sz">{fmtSize(f.size)}</span>
                  <button type="button" className="mgim-x" title="remove" onClick={() => removeFile(i)}>×</button>
                </div>
              );
            })}
            {previewCapped && (
              <div className="mgim-more">+{files.length - (CAP - 1)}<br />more</div>
            )}
          </div>

          <div className="cm-lbl" style={{ marginTop: 14 }}>ADD TO COLLECTION</div>
          <select className="cm-select" value={collection}
            onChange={(e) => setCollection(e.target.value)}>
            <option value="">— none —</option>
            {(collections || []).map((c) => <option value={c} key={c}>{c}</option>)}
            <option value={NEW_COLL}>+ New collection…</option>
          </select>
          {collection === NEW_COLL && (
            <input className="mgim-collinput" value={newCollName} autoFocus
              placeholder="collection name"
              onChange={(e) => setNewCollName(e.target.value)} />
          )}

          {result && !result.ok && <div className="mgim-result err">⚠ {result.error}</div>}

          <div className="glm-sheet-actions" style={{ marginTop: 16 }}>
            <button type="button" className="glm-primary" disabled={busy} onClick={doImport}>
              {busy ? "Importing…" : "↑ Import " + files.length + " file" + (files.length !== 1 ? "s" : "")}
            </button>
          </div>
        </>
      )}
    </>
  );
}

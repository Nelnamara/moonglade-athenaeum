import React, { useRef } from "react";
import useImport from "../hooks/useImport.js";
import "../styles/overlays.css";
import "../styles/import-overlay.css";
import useScrollLock from "../hooks/useScrollLock.js";

/* Import overlay — ported from the Frontend Gallery DC's ovImport slab
   (lines ~723-763): a file list with a collection picker, Cancel/Import N.

   The backend contract is NOT new: /api/import-local already exists, is
   localhost-only, and already has a real, working, PROVEN caller — classic's
   own `ImportUI` (moonglade_gallery.py:5953-6068, the Web Import modal).
   This is a straight port of that same logic into React, not a fresh design:
   same de-dupe (name+size), same media-only filter (image/video/zip), same
   "preview capped at 24, but every file still imports" behavior, same
   FormData({files[], collection?}) POST, same no-CSRF reasoning (SameSite +
   front-door + the route's own localhost check). The DC's markup is the
   visual target; classic's ImportUI is the behavioral one.

   Drag-and-drop + a native file/folder picker feed the same addFiles() the
   DC's markup implies but never wires (its rows are static, no real file
   input anywhere in the prototype) -- pulled from classic's real dropzone
   handling instead of invented.

   DATA LAYER (2026-08-03): the file-staging state/handlers that used to live
   inline here were mechanically lifted into useImport.js so the new mobile
   Import screen (ImportMobile.jsx) can consume the EXACT same logic -- see
   that hook's own header comment. This file is refactored to CONSUME it
   rather than hold a second, drifting copy of the same POST /api/import-local
   call. fileInputRef/folderInputRef stay local -- they're DOM refs tied to
   the two `<input>` elements this file renders (see the hook's own note on
   why those didn't move). */

export default function ImportOverlay({ onClose, collections, onImported }) {
  useScrollLock();   // page never scrolls behind a full-screen panel (2026-08-06)
  const {
    files, dragActive, setDragActive, collection, setCollection, collOpen, setCollOpen,
    newCollName, setNewCollName, busy, result, setResult,
    addFiles, removeFile, counts, summary, thumbUrl, doImport,
    previewCapped, previewList, CAP, kindOf, fmtSize, NEW_COLL,
  } = useImport({ onImported });
  const fileInputRef = useRef(null);
  const folderInputRef = useRef(null);

  return (
    <>
      <div className="mgv-scrim" onClick={onClose} />
      <div className="mgv-host">
        <div className="mgv-slab mgim-slab" role="dialog" aria-label="Import into your library"
          onDragEnter={(e) => { e.preventDefault(); setDragActive(true); }}
          onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
          onDragLeave={(e) => { e.preventDefault(); setDragActive(false); }}
          onDrop={(e) => { e.preventDefault(); setDragActive(false); if (e.dataTransfer.files) addFiles(e.dataTransfer.files); }}>
          <div className="mgv-titlerow">
            <div className="mgv-title">Import into your library</div>
            <button type="button" className="mgv-x" onClick={onClose} aria-label="Close">×</button>
          </div>
          <div className="mgim-note">
            Bring local files into the catalog — copied into <b>imported/</b> and tagged{" "}
            <b>Imported (local)</b>. Nothing is uploaded to PixAI; this is your library, not a
            generation reference.
          </div>

          {/* Hidden inputs live outside the branches below so a ref stays valid whichever
              branch is showing (needed for "Import more" to reopen the picker). */}
          <input id="mgim-file-input" ref={fileInputRef} type="file" multiple accept="image/*,video/*,.zip" style={{ display: "none" }}
            onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
          <input id="mgim-folder-input" ref={folderInputRef} type="file" multiple webkitdirectory="" style={{ display: "none" }}
            onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />

          {result && result.ok ? (
            /* Import already cleared `files` on success -- if this branch were still keyed
               off files.length===0 it would fall straight back to the drop zone and the
               confirmation would never be seen (caught live: the server logged a real
               import, the UI never showed it). */
            <div className="mgim-done">
              <div className="mgim-result ok">
                ✓ Imported <b>{result.imported}</b> file{result.imported !== 1 ? "s" : ""}
                {result.skipped ? " · " + result.skipped + " skipped (already in library)" : ""}
                {result.collection ? " · added to “" + result.collection + "”" : ""}.
              </div>
              <div className="mgim-actions">
                <button type="button" className="mgim-cancel" onClick={() => setResult(null)}>Import more</button>
                <button type="button" className="mgim-go" onClick={onClose}>Done</button>
              </div>
            </div>
          ) : files.length === 0 ? (
            <div className={"mgim-drop" + (dragActive ? " hot" : "")}>
              <div className="mgim-drop-icon">⬆</div>
              <div className="mgim-drop-text">Drop images, videos, or a .zip here</div>
              <div className="mgim-drop-buttons">
                <button type="button" className="mgim-btn" onClick={() => fileInputRef.current?.click()}>Browse files…</button>
                <button type="button" className="mgim-btn" onClick={() => folderInputRef.current?.click()}>Browse a folder…</button>
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

              <div className="mgim-collrow">
                <div className="mgim-colllbl">ADD TO COLLECTION</div>
                <div className="mgim-collpick" onClick={() => setCollOpen((v) => !v)}>
                  <span>{collection === NEW_COLL ? (newCollName || "+ New collection…") : (collection || "— none —")}</span>
                  <span className="mgim-caret">▾</span>
                </div>
                {collOpen && (
                  <div className="mgim-collmenu">
                    <div className="mgim-collopt" onClick={() => { setCollection(""); setCollOpen(false); }}>— none —</div>
                    {(collections || []).map((c) => (
                      <div className="mgim-collopt" key={c} onClick={() => { setCollection(c); setCollOpen(false); }}>{c}</div>
                    ))}
                    <div className="mgim-collopt new" onClick={() => { setCollection(NEW_COLL); setCollOpen(false); }}>
                      + New collection…
                    </div>
                  </div>
                )}
                {collection === NEW_COLL && (
                  <input className="mgim-collinput" value={newCollName} autoFocus
                    placeholder="collection name"
                    onChange={(e) => setNewCollName(e.target.value)} />
                )}
              </div>

              {result && !result.ok && <div className="mgim-result err">⚠ {result.error}</div>}

              <div className="mgim-actions">
                <button type="button" className="mgim-cancel" onClick={onClose}>Cancel</button>
                <button type="button" className="mgim-go" disabled={busy} onClick={doImport}>
                  {busy ? "Importing…" : "↑ Import " + files.length + " file" + (files.length !== 1 ? "s" : "")}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}

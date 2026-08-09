import { useEffect, useRef, useState } from "react";

/* useImport -- ImportOverlay.jsx's file-staging/upload state and handlers,
   mechanically lifted out (2026-08-03), same precedent as useMyArt.js/
   useHealth.js/useContests.js this pass (see useMyArt.js's header comment).
   ImportOverlay.jsx (desktop) is refactored to CONSUME this hook; the new
   mobile Import screen (ImportMobile.jsx) gets the identical addFiles/
   doImport/counts/summary logic and the SAME POST /api/import-local
   contract -- same de-dupe (name+size), same media-only filter, same
   "preview capped at 24, every file still imports" behavior, same
   result.ok-checked-before-files.length===0 render-order fix ImportOverlay.jsx's
   own header comment documents (the caller's JSX still has to check
   `result.ok` before `files.length === 0`, same as before -- that ordering
   lives in each component's render, not in this hook).

   Drag-and-drop stays a DESKTOP-ONLY CONCERN, not desktop-only STATE:
   `dragActive`/`setDragActive` still live here (ImportOverlay.jsx still
   needs them for its onDragEnter/Over/Leave/Drop handlers) -- nothing about
   the hook assumes a pointer device. A touch-only mobile consumer simply
   never calls setDragActive, and the drop zone it never renders never sets
   it either (see ImportMobile.jsx's header comment for the real reason
   mobile's file-picker looks different: no drag source on a touchscreen).

   fileInputRef/folderInputRef stay OUT of this hook, same reasoning
   useControlPanel.js's header comment gives for NOT lifting `tab`/
   `subOverlay`: they're DOM refs tied to specific `<input>` elements each
   consumer renders its own way (desktop: two inputs, drag zone; mobile: one
   input, no drag zone) -- a hook-owned ref pointing at a DOM node the hook
   never renders would be a leaky abstraction, not a cleaner one. */

const CAP = 24;
const IMG = /[.](png|jpe?g|webp|gif|bmp|avif)$/i;
const VID = /[.](mp4|webm|mov|m4v)$/i;
const ZIP = /[.]zip$/i;
const NEW_COLL = "__new__";

function kindOf(f) {
  const n = f.name || "";
  return ZIP.test(n) ? "zip" : VID.test(n) ? "video" : IMG.test(n) ? "image" : "other";
}
function fmtSize(b) {
  if (b < 1024) return b + " B";
  if (b < 1048576) return (b / 1024).toFixed(0) + " KB";
  if (b < 1073741824) return (b / 1048576).toFixed(1) + " MB";
  return (b / 1073741824).toFixed(2) + " GB";
}

export default function useImport({ onImported } = {}) {
  const [files, setFiles] = useState([]);
  const [dragActive, setDragActive] = useState(false);
  const [collection, setCollection] = useState("");
  const [collOpen, setCollOpen] = useState(false);
  const [newCollName, setNewCollName] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const urlsRef = useRef([]);

  useEffect(() => () => { urlsRef.current.forEach((u) => URL.revokeObjectURL(u)); }, []);

  const addFiles = (list) => {
    const next = files.slice();
    for (const f of Array.from(list)) {
      if (kindOf(f) === "other") continue; // media only, matches classic
      if (next.some((x) => x.name === f.name && x.size === f.size)) continue; // de-dupe
      next.push(f);
    }
    setFiles(next);
    setResult(null);
  };
  const removeFile = (i) => setFiles(files.filter((_, idx) => idx !== i));

  const counts = files.reduce((acc, f) => {
    const k = kindOf(f);
    acc[k] = (acc[k] || 0) + 1;
    acc.bytes += f.size;
    return acc;
  }, { bytes: 0 });
  const summary = [
    counts.image ? counts.image + " image" + (counts.image !== 1 ? "s" : "") : "",
    counts.video ? counts.video + " video" + (counts.video !== 1 ? "s" : "") : "",
    counts.zip ? counts.zip + " zip" + (counts.zip !== 1 ? "s" : "") : "",
  ].filter(Boolean).join(" · ");

  urlsRef.current.forEach((u) => URL.revokeObjectURL(u));
  urlsRef.current = [];
  const thumbUrl = (f) => {
    if (kindOf(f) !== "image") return null;
    const u = URL.createObjectURL(f);
    urlsRef.current.push(u);
    return u;
  };

  const chosenCollection = () => {
    if (collection !== NEW_COLL) return collection;
    const name = newCollName.trim();
    return name || null;
  };

  const doImport = async () => {
    if (!files.length || busy) return;
    const coll = chosenCollection();
    if (coll === null) { setCollOpen(true); return; } // "New collection…" left blank
    setBusy(true);
    setResult(null);
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f, f.name));
    if (coll) fd.append("collection", coll);
    try {
      const r = await fetch("/api/import-local", { method: "POST", body: fd });
      const d = await r.json();
      setBusy(false);
      if (!r.ok || d.error) {
        setResult({ ok: false, error: d.error || ("import failed (" + r.status + ")") });
        return;
      }
      setResult({ ok: true, imported: d.imported, skipped: d.skipped, collection: d.collection });
      setFiles([]);
      onImported && onImported();
    } catch {
      setBusy(false);
      setResult({ ok: false, error: "network error" });
    }
  };

  const previewCapped = files.length > CAP;
  const previewList = previewCapped ? files.slice(0, CAP - 1) : files;

  return {
    files, setFiles, dragActive, setDragActive,
    collection, setCollection, collOpen, setCollOpen, newCollName, setNewCollName,
    busy, result, setResult,
    addFiles, removeFile, counts, summary, thumbUrl, chosenCollection, doImport,
    previewCapped, previewList, CAP, kindOf, fmtSize, NEW_COLL,
  };
}

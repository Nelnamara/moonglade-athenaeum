import React, { useCallback, useEffect, useRef, useState } from "react";
import PickerCore from "../picker/pickerCore.js";
import "../styles/gallery-picker.css";

/* Faithful React port of static/mg-gallery-picker.js (2026-08-08, the vanilla static/ ->
   React campaign). The "pick an image from your catalog" modal: search + collection/type/
   rating/sort filters, infinite scroll (via PickerCore), optional upload, persisted
   tile-size + copy-prompt, NSFW blur, and the both-ways glass animation. Behaviour is 1:1
   with the old custom element -- this is a port, not a redesign (a Claude Design pass is
   flagged for later). Contract mirrors the element's events:
     onPick(media)  fires INSTANTLY on pick (the fast path; parent tears down immediately)
     onClose()      fires after the 340ms exit animation (Escape / backdrop / X), so the
                    parent unmounts AFTER the exit finishes instead of snapping it mid-frame.
   media shape: {media_id, thumb, prompt, is_video, duration, is_nsfw}. */

const COPY_KEY = "pick-copyprompt";   // localStorage: "copy prompt on pick" (shared by every picker)
const TILE_KEY = "mg-pk-tile";        // localStorage: persisted thumbnail size

function readTile() { try { return +localStorage.getItem(TILE_KEY) || 122; } catch { return 122; } }
function readCopy() { try { return localStorage.getItem(COPY_KEY) === "1"; } catch { return false; } }

export default function GalleryPicker({
  defaultType = "image", showType = false, showSource = false,
  showUpload = false, showCopyPrompt = false, sheet = false,
  onPick, onClose,
}) {
  // 'all' is a REAL value (server maps '' -> image for back-compat); resolve like the element did.
  const initType = defaultType === "video" ? "video" : defaultType === "all" ? "all" : "image";

  const [images, setImages] = useState([]);
  const [collections, setCollections] = useState([]);
  const [total, setTotal] = useState(0);
  const [empty, setEmpty] = useState(false);
  const [closing, setClosing] = useState(false);
  const [uploadMsg, setUploadMsg] = useState(null);

  const [type, setType] = useState(initType);
  const [collection, setCollection] = useState("");
  const [source, setSource] = useState("");
  const [rating, setRating] = useState(0);
  const [sort, setSort] = useState("newest");
  const [q, setQ] = useState("");

  const [tile, setTile] = useState(readTile);
  const [copyOn, setCopyOn] = useState(readCopy);

  const coreRef = useRef(null);
  const gridRef = useRef(null);
  const qRef = useRef(null);
  const fileRef = useRef(null);
  const debounceRef = useRef(null);
  const closingRef = useRef(false);
  // Freshest filter values for the debounced push -- reassigned every render off state, so
  // the 160ms timeout (which fires long after the re-render) always reads current values.
  const fRef = useRef();
  fRef.current = { q, collection, type, source, rating_min: rating, sort };

  // ---- PickerCore lifecycle: created ONCE; browse-on-open fires immediately (not debounced) ----
  useEffect(() => {
    const core = PickerCore.create({
      defaultFilters: { type: initType, collection: "", source: "", rating_min: 0, sort: "newest" },
      onResults: (imgs, meta) => {
        setTotal(meta.total || 0);
        if (meta.append) {
          setImages((old) => old.concat(imgs));
        } else {
          setUploadMsg(null);           // a fresh search clears any stale upload message
          setImages(imgs);
          setEmpty(!imgs.length);
        }
      },
      onCollections: (colls) => setCollections(colls || []),
      onError: () => {},
    });
    coreRef.current = core;
    core.fetchCollections();
    core.setFilters({ q: "", collection: "", type: initType, source: "", rating_min: 0, sort: "newest" });
    const t = setTimeout(() => qRef.current && qRef.current.focus(), 60);
    return () => { clearTimeout(t); core.destroy(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // After each results render, pull one more page if the grid doesn't overflow yet (no
  // scrollbar => infinite scroll can't fire). PickerCore caps this so it can't runaway.
  useEffect(() => {
    if (coreRef.current) coreRef.current.maybeFillPage(gridRef.current);
  }, [images]);

  useEffect(() => { try { localStorage.setItem(TILE_KEY, String(tile)); } catch { /* private mode */ } }, [tile]);

  // ONE combined 160ms debounce over q + every select (matches the element's _schedule()).
  const schedule = useCallback(() => {
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      if (coreRef.current) coreRef.current.setFilters(fRef.current);
    }, 160);
  }, []);

  const toggleCopy = (checked) => {
    setCopyOn(checked);
    try { localStorage.setItem(COPY_KEY, checked ? "1" : "0"); } catch { /* private mode */ }
  };

  // Close animates BOTH ways: .mg-closing plays the exit, onClose() is deferred 340ms so the
  // parent's unmount lands after it. Re-entry (Esc mashed / backdrop re-clicked) is a no-op.
  const doClose = useCallback(() => {
    if (closingRef.current) return;
    closingRef.current = true;
    setClosing(true);
    setTimeout(() => onClose && onClose(), 340);
  }, [onClose]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") doClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [doClose]);

  // Pick is the fast path -- fires instantly, NOT deferred (parent tears down immediately).
  const pick = (m) => {
    if (copyOn && m.prompt) {
      try { navigator.clipboard && navigator.clipboard.writeText(m.prompt); } catch { /* clipboard denied */ }
    }
    onPick && onPick({
      media_id: m.media_id, thumb: m.thumb, prompt: m.prompt || "",
      is_video: m.is_video === "1", duration: m.duration || "", is_nsfw: m.is_nsfw === "1",
    });
  };

  const doUpload = () => {
    const f = fileRef.current && fileRef.current.files[0];
    if (!f) return;
    setUploadMsg("Uploading " + f.name + "…");
    const fd = new FormData(); fd.append("file", f);
    fetch("/api/upload", { method: "POST", body: fd }).then((r) => r.json()).then((d) => {
      if (fileRef.current) fileRef.current.value = "";
      if (d.error || !d.media_id) { setUploadMsg("⚠ Upload failed: " + (d.error || "no media id")); return; }
      setUploadMsg(null);
      pick({ media_id: d.media_id, prompt: "", thumb: URL.createObjectURL(f) });
    }).catch(() => {
      if (fileRef.current) fileRef.current.value = "";
      setUploadMsg("⚠ Upload failed (network).");
    });
  };

  const cls = "mg-gallery-picker" + (sheet ? " sheet" : "") + (closing ? " mg-closing" : "");
  return (
    <div className={cls} style={{ "--mg-pk-tile": tile + "px" }}
      onClick={(e) => { if (e.target === e.currentTarget) doClose(); }}>
      <div className="mg-pk-box" role="dialog" aria-label="Pick from your gallery">
        <div className="mg-pk-head">
          <span className="mg-pk-t">Pick from your gallery</span>
          <input ref={qRef} className="mg-pk-q" type="text" placeholder="Search your images…"
            value={q} onChange={(e) => { setQ(e.target.value); schedule(); }} />
          <button type="button" className="mg-pk-x" data-tip="Close (Esc)" aria-label="Close (Esc)"
            onClick={doClose}>&#215;</button>
        </div>
        <div className="mg-pk-filters">
          <select data-f="collection" value={collection}
            onChange={(e) => { setCollection(e.target.value); schedule(); }}>
            <option value="">All collections</option>
            {collections.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          {showType && (
            <select data-f="type" value={type} onChange={(e) => { setType(e.target.value); schedule(); }}>
              <option value="all">Image + video</option>
              <option value="image">Images</option>
              <option value="video">Videos</option>
            </select>
          )}
          {showSource && (
            <select data-f="source" value={source} onChange={(e) => { setSource(e.target.value); schedule(); }}>
              <option value="">Any source</option>
              <option value="api">Generated (AI)</option>
              <option value="local">Imported local</option>
            </select>
          )}
          <select data-f="rating" value={rating} onChange={(e) => { setRating(+e.target.value); schedule(); }}>
            <option value="0">Any rating</option>
            <option value="1">★+</option>
            <option value="2">★★+</option>
            <option value="3">★★★+</option>
            <option value="4">★★★★+</option>
            <option value="5">★★★★★</option>
          </select>
          <select data-f="sort" value={sort} onChange={(e) => { setSort(e.target.value); schedule(); }}>
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
          </select>
          {showUpload && (
            <>
              <button type="button" className="mg-pk-upload"
                onClick={() => fileRef.current && fileRef.current.click()}>＋ Upload</button>
              <input ref={fileRef} type="file" className="mg-pk-file" accept="image/*"
                style={{ display: "none" }} onChange={doUpload} />
            </>
          )}
          <label className="mg-pk-sizer">Size
            <input type="range" min="90" max="240" step="8" title="Thumbnail size"
              value={tile} onChange={(e) => setTile(+e.target.value)} />
          </label>
          <span className="mg-pk-count">{(total || 0).toLocaleString()}</span>
        </div>
        {showCopyPrompt && (
          <label className="mg-pk-copy">
            <input type="checkbox" className="mg-pk-copyck" checked={copyOn}
              onChange={(e) => toggleCopy(e.target.checked)} /> Copy prompt on pick
          </label>
        )}
        <div className="mg-pk-grid" ref={gridRef}
          onScroll={() => coreRef.current && coreRef.current.onScroll(gridRef.current, 280)}>
          {images.map((m, i) => (
            <div key={m.media_id + ":" + i} className="mg-pk-cell" title={m.prompt || m.media_id}
              data-nsfw={m.is_nsfw === "1" ? "1" : undefined} onClick={() => pick(m)}>
              <img loading="lazy" decoding="async" src={m.thumb} alt="" />
              {m.is_video === "1" && <span className="mg-pk-vid">▶</span>}
            </div>
          ))}
        </div>
        {(empty || uploadMsg) && (
          <div className="mg-pk-empty">{uploadMsg || "No matches for these filters."}</div>
        )}
      </div>
    </div>
  );
}

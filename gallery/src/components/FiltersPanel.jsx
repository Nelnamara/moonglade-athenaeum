import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { askPicker } from "./PickerHost.jsx";

/* Adaptive side-by-side placement, mirroring classic's placeFilters(). The
   pilot's drawer only ever docks right (no dock-switching here), so there is
   only ever a LEFT side to try -- below AF_MIN_SIDE there is no honest
   side-by-side left (the rail alone is 236px), so it centres over the
   viewport instead, matching #model-flyout's own documented fallback for
   docks with no room beside them. Two pictures are worth judging from about
   380px each: 380*2 + 236 (rail) + 28 (gaps) + 26 (padding) = 1050. */
const AF_W = 1180, AF_MIN_SIDE = 1050;

/* Art filters -- what REPLACED the Enhance surface (owner, 2026-07-29: "Art
   filters replaced enhance. no need to rebuild [enhance]").

   This is a FLOATING panel beside the drawer, matching classic's
   #filters-flyout -- NOT a tab body (owner QA 2026-07-30: "it opens a
   floating panel in classic, you added it to the drawer inline"). Original
   and Preview render side by side so a filter is judged by comparison, not
   by toggling No filter back and forth from memory. #af-orig-equivalent is a
   SECOND <img> of the same /full/ url rather than a clone of the preview's:
   the preview image is what MgArtFilters mutates (a CSS filter, overlay divs
   at inset:0), and anything sharing that element would be filtered too,
   leaving nothing to compare against. Same-origin and already cached, so the
   second one costs a cache hit, not a download.

   These are NOT generations: window.MgArtFilters composites gradient layers
   in the browser, so nothing is sent, nothing is spent, and it works
   offline. Only the two exits touch the server -- Save (POST
   /api/import-local, local library write) and Send to image gen (POST
   /api/upload, a free S3 handshake). Deliberately keeps its OWN source pick
   rather than sharing the Edit tab's (that state lives inside EditTab, not
   lifted to the drawer) -- comparing a filter doesn't require committing to
   an edit source first. */
export default function FiltersPanel({ open, onClose, drawerRef, onSendToEdit }) {
  const AF = typeof window !== "undefined" ? window.MgArtFilters : null;
  const [source, setSource] = useState("");
  const [active, setActive] = useState(null);
  const [strength, setStrength] = useState(1);
  const [angle, setAngle] = useState(180);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const panelRef = useRef(null);
  const stageRef = useRef(null);
  const imgRef = useRef(null);
  const railRef = useRef(null);

  const opts = useCallback(() => ({ strength: Number(strength), angle: Number(angle) }), [strength, angle]);

  // swatch tiles, grouped -- painted by the library itself, built once per open panel
  useEffect(() => {
    if (!open || !AF || !railRef.current) return;
    const rail = railRef.current;
    if (rail.firstChild) return;
    AF.groups().forEach((grp) => {
      const head = document.createElement("div");
      head.className = "af-grp";
      head.textContent = grp.label;
      rail.appendChild(head);
      const grid = document.createElement("div");
      grid.className = "af-tiles";
      rail.appendChild(grid);
      grp.ids.forEach((id) => {
        const rec = AF.get(id) || {};
        const tile = document.createElement("button");
        tile.type = "button";
        tile.className = "af-tile";
        tile.title = (rec.name || id) + " · free, applied in your browser" + (rec.note ? " — " + rec.note : "");
        tile.dataset.afid = id;
        const sw = document.createElement("div");
        sw.className = "sw";
        const cap = document.createElement("div");
        cap.className = "cap";
        cap.textContent = (rec.name || id).replace("Filter ", "");
        tile.appendChild(sw);
        tile.appendChild(cap);
        grid.appendChild(tile);
        AF.renderSwatch(sw, id); // the tile IS that filter's own gradients, no art needed
      });
    });
  }, [open, AF]);

  /* Clicks on the rail, delegated so imperatively-painted tiles work. `open`
     MUST be in the deps: this component returns null while closed, so on the
     first run railRef.current is null and the listener binds to nothing --
     without re-running on the closed->open flip, every tile click is
     swallowed (the exact gotcha that bit the earlier inline build). */
  useEffect(() => {
    const rail = railRef.current;
    if (!rail) return;
    const onClick = (e) => {
      const t = e.target.closest && e.target.closest(".af-tile");
      if (t) setActive((cur) => (t.dataset.afid === cur ? null : t.dataset.afid));
    };
    rail.addEventListener("click", onClick);
    return () => rail.removeEventListener("click", onClick);
  }, [open]);

  useEffect(() => {
    const rail = railRef.current;
    if (!rail) return;
    rail.querySelectorAll(".af-tile").forEach((t) => {
      t.classList.toggle("on", t.dataset.afid === active);
    });
  }, [active, open]);

  // (re)apply the live preview -- pure CSS overlays, no pixels copied
  useEffect(() => {
    if (!open || !AF || !stageRef.current) return;
    const host = stageRef.current;
    AF.clearPreview(host);
    if (!active) { setMsg(source ? "" : "Pick an image first — then this filter previews over it."); return; }
    if (!source) { setMsg("Pick an image first — then this filter previews over it."); return; }
    const n = AF.applyPreview(host, active, opts());
    const rec = AF.get(active) || {};
    // normalizeLayers reports any layer it had to drop (an unmapped blend mode, a stop
    // colour that isn't a plain literal) -- the preview still renders, just without that
    // layer, so saying so is the difference between "this looks off" and a silent wrong result.
    setMsg(n.warnings && n.warnings.length ? n.warnings[0] : (rec.name || active) + " · nothing sent, nothing spent");
  }, [AF, active, source, opts, open]);

  /* Placement follows the drawer's own rect -- called on open, on either
     image's load (the panel's height depends on the picture's rendered
     height), and on resize. Two-pass like the classic: write width first,
     THEN measure offsetHeight (needs .open and the width already applied),
     THEN write left/top. */
  const place = useCallback(() => {
    const f = panelRef.current, d = drawerRef.current;
    if (!f || !d) return;
    const r = d.getBoundingClientRect();
    const vw = window.innerWidth, vh = window.innerHeight, pad = 8, gap = 10;
    const leftRoom = r.left - gap - pad;
    let w, x;
    if (leftRoom >= AF_MIN_SIDE) { w = Math.min(AF_W, leftRoom); x = r.left - gap - w; }
    else { w = Math.min(AF_W, vw - pad * 2); x = (vw - w) / 2; }
    f.style.width = Math.round(w) + "px";
    f.style.maxHeight = (vh - pad * 2) + "px";
    const h = f.offsetHeight;
    f.style.left = Math.round(Math.max(pad, x)) + "px";
    f.style.top = Math.round(Math.max(pad, Math.min(r.top + 8, vh - h - pad))) + "px";
  }, [drawerRef]);

  useLayoutEffect(() => { if (open) place(); }, [open, place]);

  useEffect(() => {
    if (!open) return;
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [open, place]);

  const pickSource = async () => {
    const m = await askPicker({ type: "image" });
    if (m) { setSource(m.media_id); setActive(null); }
  };

  const bake = async () => {
    if (!AF || !imgRef.current || !active) return null;
    return AF.toBlob(imgRef.current, active, opts());
  };

  const save = async () => {
    if (!active) { setMsg("Pick a filter first."); return; }
    setBusy(true);
    try {
      const blob = await bake();
      if (!blob) return;
      const fd = new FormData();
      // Strength/angle are part of the OUTPUT, not just the filter id -- without them in
      // the name, re-saving the same filter at a different slider position collides with
      // the first file's name and run_import_local's path-based dedup silently treats a
      // genuinely different image as the same one (owner 2026-07-29: "wont save its new
      // image... writing the same filename" -- confirmed against run_import_local, which
      // keys purely on filename, not content).
      const tag = active + "_s" + Number(strength).toFixed(2).replace(".", "") + "_a" + angle;
      fd.append("files", blob, source + "_" + tag + ".png");
      const r = await fetch("/api/import-local", { method: "POST", body: fd });
      const d = await r.json();
      if (d.error) {
        const friendly = r.status === 403
          ? "This only works when you're at the machine running the server — not over LAN/tablet."
          : d.error;
        setMsg(friendly);
        if (window.Toast) window.Toast.show({ kind: "err", title: "Not saved", msg: friendly });
        return;
      }
      const text = d.imported ? "Saved to your library." : "Already in your library (a duplicate).";
      setMsg(text);
      if (window.Toast) window.Toast.show({ kind: d.imported ? "ok" : "", title: text });
      if (d.imported) window.dispatchEvent(new CustomEvent("mg-gen-done"));
    } catch (e) {
      const m = "Couldn't save: " + (e && e.message ? e.message : "unknown error");
      setMsg(m);
      if (window.Toast) window.Toast.show({ kind: "err", title: "Not saved", msg: m });
    } finally { setBusy(false); }
  };

  const sendToEdit = async () => {
    if (!active) { setMsg("Pick a filter first."); return; }
    setBusy(true);
    try {
      const blob = await bake();
      if (!blob) return;
      const fd = new FormData();
      fd.append("file", blob, "filtered_" + active + ".png");
      const d = await fetch("/api/upload", { method: "POST", body: fd }).then((r) => r.json());
      if (d.error || !d.media_id) { setMsg(d.error || "Upload failed."); return; }
      const name = (AF.get(active) || {}).name || active;
      onClose();
      onSendToEdit(d.media_id);
      if (window.Toast) {
        window.Toast.show({ kind: "ok", title: "Filtered image is your edit source", msg: name + " · uploaded free, nothing generated yet" });
      }
    } catch (e) {
      setMsg("Couldn't send: " + (e && e.message ? e.message : "unknown error"));
    } finally { setBusy(false); }
  };

  if (!open) return null;
  return (
    <div className="af-panel" ref={panelRef} role="dialog" aria-label="Art filters">
      <div className="gd-head">
        <span className="gd-lbl" style={{ fontSize: 13, letterSpacing: 0, textTransform: "none" }}>&#9673; Art filters</span>
        <span className="sp" />
        <button className="card" onClick={onClose} aria-label="Close">&times;</button>
      </div>
      {!AF ? (
        <div className="gd-note">The art-filter library did not load on this page.</div>
      ) : (
        <div className="af-wrap">
          <div className="af-col">
            <div className="af-frame">
              <img alt="the unfiltered original" src={source ? "/full/" + encodeURIComponent(source) : undefined} onLoad={place} />
            </div>
            <div className="af-cap">Original</div>
          </div>
          <div className="af-col">
            <div className="af-frame">
              <div className="af-stage" ref={stageRef}>
                <img ref={imgRef} alt="filtered preview" src={source ? "/full/" + encodeURIComponent(source) : undefined} onLoad={place} />
              </div>
            </div>
            <div className="af-cap">Preview &middot; <b>{active ? (AF.get(active) || {}).name || active : "no filter"}</b></div>
          </div>
          <div className="af-rail">
            <div className="gd-row">
              <button className="card" onClick={pickSource}>{source ? "▨ Change" : "▨ Pick"}</button>
              <span className="gd-note">free · local</span>
            </div>
            <div ref={railRef} />
            <div className="gd-lbl">Strength <span style={{ color: "var(--lavender, var(--accent))" }}>{Number(strength).toFixed(2)}</span></div>
            <input type="range" min="0" max="1" step="0.01" value={strength}
              onChange={(e) => setStrength(e.target.value)} />
            <div className="gd-lbl">Angle <span style={{ color: "var(--lavender, var(--accent))" }}>{angle}&deg;</span></div>
            <input type="range" min="0" max="345" step="15" value={angle}
              onChange={(e) => setAngle(e.target.value)} />
            <div className="af-acts">
              <button type="button" className="card" onClick={() => setActive(null)}>No filter</button>
              <button type="button" className="gen" disabled={!active || !source || busy} onClick={save}>Save to library</button>
              <button type="button" className="card" disabled={!active || !source || busy} onClick={sendToEdit}
                title="Upload the filtered image to PixAI (free) and load it as the Edit source">
                Send to image gen
              </button>
              <button type="button" className="card" disabled title="Publishing to PixAI is not built yet">Publish</button>
            </div>
            {msg && <div className="af-msg">{msg}</div>}
          </div>
        </div>
      )}
    </div>
  );
}

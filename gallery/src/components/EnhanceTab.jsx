import React, { useEffect, useRef, useState } from "react";
import { submitTask, useResultLines } from "../gen/submitTask.js";
import { ResultLines } from "./EditTab.jsx";

/* The Enhance sub-tab, built to PixAI's real Enhance surface (labeled capture
   `enhance__preset-tab.png`) adapted to the drawer: a grid of the six panelplugin presets
   with their REAL thumbnails, SELECTABLE (not submit-on-click), then one "Generate ✦ <cost>"
   button that runs the selected preset on the SOURCE image (slab 1). Mirror off -> only the
   free art filters (§2). Cost chips are live (/api/enhance/presets); tiles paint instantly
   from SKELETON and fill in when the priced list lands. */

// Real preset thumbnails, captured from pixai.art. Source lives in gallery/public/bridge/*.png;
// vite copies it to gallery/dist/bridge/, and the app serves dist via /next/assets/<path> (the
// same base app.js/app.css load from), so the served URL is /next/assets/bridge/*.png.
const THUMB = {
  handfix: "/next/assets/bridge/preset_handfix.png",
  face: "/next/assets/bridge/preset_face-enhance.png",
  emotion: "/next/assets/bridge/preset_change-emotion.png",
  bg_remove: "/next/assets/bridge/preset_background-remover.png",
  line_art: "/next/assets/bridge/preset_line-art.png",
  sketch_color: "/next/assets/bridge/preset_sketch-coloring.png",
};
const SKELETON = [
  { key: "handfix", label: "Handfix" }, { key: "face", label: "Face Enhance" },
  { key: "emotion", label: "Change Emotion" }, { key: "bg_remove", label: "Background Remover" },
  { key: "line_art", label: "Convert to Line Art" }, { key: "sketch_color", label: "Sketch Coloring" },
];
// The comp's free-filter swatch teaser; the real compare/apply panel opens via onOpenFilters.
const FREE_FILTERS = [
  ["Moonglade", "#b692e6", "#4fc99a"], ["Nightfallen", "#a678f0", "#33236d"],
  ["Moonlit", "#8fb8e8", "#cfe1f5"], ["Ember", "#e8935f", "#ffcf7a"],
  ["Verdant", "#5fd39a", "#c8e6a8"], ["M1", "#f38ba8", "#fab387"],
  ["M2", "#47cbc3", "#3a8a93"], ["M3", "#d4af37", "#a11238"],
  ["M4", "#f5a97f", "#ffd9b8"], ["M5", "#f8d8b0", "#fff3e0"],
  ["M6", "#e88a6b", "#f7c59f"], ["M7", "#a8c5f0", "#dbe8ff"],
];

export default function EnhanceTab({ source, armed, onOpenFilters }) {
  const [presets, setPresets] = useState(null);   // null = loading; [] = load failed
  const [sel, setSel] = useState("handfix");       // Handfix selected by default, like the real surface
  const [lines, openLine] = useResultLines();
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);

  useEffect(() => {
    if (!armed) { setPresets(null); return undefined; }
    let live = true;
    fetch("/api/enhance/presets")
      .then((r) => r.json())
      .then((d) => { if (live) setPresets((d && d.presets) || []); })
      .catch(() => { if (live) setPresets([]); });
    return () => { live = false; };
  }, [armed]);

  const loading = presets === null;
  const rows = presets && presets.length ? presets : SKELETON;
  const selRow = rows.find((p) => p.key === sel) || rows[0];
  const priced = presets ? presets.find((p) => p.key === sel) : null;  // carries price + addressing

  const cost = (p) => !p ? ""
    : p.free_card ? "✦ free card"
      : p.price != null ? "◆ " + Number(p.price).toLocaleString() : "";

  const run = async () => {
    if (busyRef.current || loading || !priced) return;
    if (!source) {
      if (window.Toast) {
        window.Toast.show({ kind: "err", title: "Pick a source first",
          msg: "Add an image in SOURCE above, then Generate." });
      }
      return;
    }
    const q = priced.free_card ? "a free card covers it — 0 credits"
      : priced.price != null ? "this will spend " + Number(priced.price).toLocaleString() + " credits"
        : "this spends credits";
    if (!window.confirm(priced.label + " on your source?\n\n" + q + " — runs on the PixAI mirror.")) return;
    busyRef.current = true; setBusy(true);
    const emit = openLine("Submitting " + priced.label + "…");
    const body = priced.workflow_name
      ? { source, workflow_name: priced.workflow_name }
      : { source, workflow_id: priced.workflow_id };
    await submitTask("/api/enhance", body, { label: priced.label, emit });
    busyRef.current = false; setBusy(false);
  };

  const genOff = !source || loading || busy || !priced;

  return (
    <div className="mgdock-slab mgdock-enhslab">
      {armed && (
        <>
          <div className="mgdock-ailbl">
            <span className="mgdock-aikick">AI PRESETS · via the Bridge</span>
            <span className="sp" />
            <span className="mgdock-aimirror">● runs on the mirror</span>
          </div>

          <div className="mgdock-aigrid">
            {rows.map((p) => (
              <button key={p.key} type="button"
                className={"mgdock-aitile" + (sel === p.key ? " on" : "")}
                onClick={() => setSel(p.key)} title={p.label}>
                <img className="mgdock-aithumb" src={THUMB[p.key]} alt="" loading="lazy" />
                <span className="mgdock-aimeta">
                  <span className="mgdock-ainame">{p.label}</span>
                  <span className={"mgdock-aicost" + (loading ? " ph" : "")}>{loading ? "◆ ·····" : cost(p)}</span>
                </span>
              </button>
            ))}
          </div>

          <button type="button" className={"mgdock-enhgen" + (genOff ? " off" : "")} disabled={genOff}
            title={!source ? "Add a source image in SOURCE above"
              : loading ? "Pricing…" : "Generate " + selRow.label + " — runs on the mirror"}
            onClick={run}>
            <span>&#10022; Generate {selRow ? selRow.label : ""}</span>
            <span className="mgdock-enhgencost">{loading ? "…" : cost(priced)}</span>
          </button>

          <div className="mgdock-enhsecs">Dispatches in <b>seconds</b> — the gate was the
            credential, not the feature.</div>
          <ResultLines lines={lines} />
          <div className="mgdock-enhdiv" />
        </>
      )}

      {/* FREE FILTERS — always; mirror-independent, offline, no credits */}
      <div className="mgdock-enhsub">FREE FILTERS · offline, no credits</div>
      <div className="mgdock-swgrid">
        {FREE_FILTERS.map(([label, a, b]) => (
          <span key={label} className="mgdock-sw" title={label}
            style={{ background: "linear-gradient(135deg, " + a + ", " + b + ")" }} />
        ))}
      </div>
      <button type="button" className="mgdock-enhcompare" onClick={onOpenFilters}>◐ Open compare view — M1–M7</button>
    </div>
  );
}

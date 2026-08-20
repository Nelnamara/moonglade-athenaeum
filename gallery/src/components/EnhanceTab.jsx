import React, { useEffect, useRef, useState } from "react";
import { submitTask, useResultLines } from "../gen/submitTask.js";
import { ResultLines } from "./EditTab.jsx";

/* The Enhance sub-tab, built to PixAI's real Enhance surface (labeled capture
   `enhance__preset-tab.png`) adapted to the drawer: a grid of the six panelplugin presets
   with their REAL thumbnails, SELECTABLE (not submit-on-click), then one "Generate ✦ <cost>"
   button that runs the selected preset on the SOURCE image (slab 1). Mirror off -> only the
   free art filters (§2). Cost chips are live (/api/enhance/presets); tiles paint instantly
   from SKELETON and fill in when the priced list lands. */

// Real preset thumbnails, packaged like every other branding-class asset in this app: NOT
// committed to the repo -- they live in the shipped asset container (moonglade.dat) as
// bridge/preset_*.webp, resolved loose-then-container and served via /branding/<path>. On a box
// without the container (or a fresh install before its download), the route 404s and onError
// hides the <img> so the tile still reads (name + cost), matching the branding contract.
const THUMB = {
  handfix: "/branding/bridge/preset_handfix.webp",
  face: "/branding/bridge/preset_face-enhance.webp",
  emotion: "/branding/bridge/preset_change-emotion.webp",
  bg_remove: "/branding/bridge/preset_background-remover.webp",
  line_art: "/branding/bridge/preset_line-art.webp",
  sketch_color: "/branding/bridge/preset_sketch-coloring.webp",
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
  const [emotions, setEmotions] = useState(null);   // Change Emotion options; null = not loaded
  const [emotionKey, setEmotionKey] = useState("");

  useEffect(() => {
    if (!armed) { setPresets(null); return undefined; }
    let live = true;
    fetch("/api/enhance/presets")
      .then((r) => r.json())
      .then((d) => { if (live) setPresets((d && d.presets) || []); })
      .catch(() => { if (live) setPresets([]); });
    return () => { live = false; };
  }, [armed]);

  // Lazily load the staged Change-Emotion options the first time that preset is opened.
  useEffect(() => {
    if (!armed || sel !== "emotion" || emotions !== null) return undefined;
    let live = true;
    fetch("/api/enhance/emotions")
      .then((r) => r.json())
      .then((d) => { if (live) setEmotions((d && d.emotions) || []); })
      .catch(() => { if (live) setEmotions([]); });
    return () => { live = false; };
  }, [armed, sel, emotions]);

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
    if (sel === "emotion" && emotionKey) body.emotion = emotionKey;
    await submitTask("/api/enhance", body, { label: priced.label, emit });
    busyRef.current = false; setBusy(false);
  };

  // Only block on picking an expression when options are actually staged; with none staged,
  // the preset still runs on PixAI's default emotion (unchanged behaviour).
  const needEmotion = sel === "emotion" && Array.isArray(emotions) && emotions.length > 0 && !emotionKey;
  const genOff = !source || loading || busy || !priced || needEmotion;

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
                <img className="mgdock-aithumb" src={THUMB[p.key]} alt="" loading="lazy"
                  onError={(e) => { e.currentTarget.style.display = "none"; }} />
                <span className="mgdock-aimeta">
                  <span className="mgdock-ainame">{p.label}</span>
                  <span className={"mgdock-aicost" + (loading ? " ph" : "")}>{loading ? "◆ ·····" : cost(p)}</span>
                </span>
              </button>
            ))}
          </div>

          {sel === "emotion" && (
            <div className="mgdock-emopick">
              <div className="mgdock-enhsub">TARGET EXPRESSION</div>
              {emotions === null ? (
                <div className="mgdock-enhsecs">Loading expressions…</div>
              ) : emotions.length === 0 ? (
                <div className="mgdock-enhsecs">No expression art staged yet — drop images into
                  {" "}<b>branding/bridge/emotion/</b> (one per emotion).</div>
              ) : (
                <div className="mgdock-aigrid">
                  {emotions.map((e) => (
                    <button key={e.key} type="button"
                      className={"mgdock-aitile" + (emotionKey === e.key ? " on" : "")}
                      onClick={() => setEmotionKey(e.key)} title={e.label}>
                      <img className="mgdock-aithumb" src={e.img} alt="" loading="lazy"
                        onError={(ev) => { ev.currentTarget.style.display = "none"; }} />
                      <span className="mgdock-aimeta"><span className="mgdock-ainame">{e.label}</span></span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          <button type="button" className={"mgdock-enhgen" + (genOff ? " off" : "")} disabled={genOff}
            title={!source ? "Add a source image in SOURCE above"
              : needEmotion ? "Pick a target expression first"
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

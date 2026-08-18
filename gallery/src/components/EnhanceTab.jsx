import React, { useEffect, useRef, useState } from "react";
import { submitTask, useResultLines } from "../gen/submitTask.js";
import { ResultLines } from "./EditTab.jsx";

/* The Enhance sub-tab, built to The Bridge.dc.html §3 ("Enhance — home, in the drawer"):
   ONE slab that, when the mirror is armed, stacks the six panelplugin AI presets, the Change
   Emotion thumbnail control, a "dispatches in seconds" note, then the free art-filter swatches
   and the compare-view button. Mirror OFF -> only the free filters show (§2, "as it does
   today"). Cost chips are LIVE and honest (from /api/enhance/presets); the six tiles render
   INSTANTLY as skeletons and the prices fill in when the fetch lands, so the slab never blocks. */

// Rendered instantly so the slab has its shape with zero wait; the fetch replaces this with the
// live-priced list. Labels/keys/has_control only -- no addressing here, so a tile can't be
// submitted until the real (priced) list arrives (tiles stay disabled until then).
const SKELETON = [
  { key: "handfix", label: "Handfix", has_control: false },
  { key: "face", label: "Face Enhance", has_control: false },
  { key: "emotion", label: "Change Emotion", has_control: true },
  { key: "bg_remove", label: "Background Remover", has_control: false },
  { key: "line_art", label: "Convert to Line Art", has_control: false },
  { key: "sketch_color", label: "Sketch Coloring", has_control: false },
];

// The comp's twelve free-filter swatches (enhanceFilters) -- a visual teaser; the real
// compare/apply panel opens via onOpenFilters (the existing FilterCompare overlay).
const FREE_FILTERS = [
  ["Moonglade", "#b692e6", "#4fc99a"], ["Nightfallen", "#a678f0", "#33236d"],
  ["Moonlit", "#8fb8e8", "#cfe1f5"], ["Ember", "#e8935f", "#ffcf7a"],
  ["Verdant", "#5fd39a", "#c8e6a8"], ["M1", "#f38ba8", "#fab387"],
  ["M2", "#47cbc3", "#3a8a93"], ["M3", "#d4af37", "#a11238"],
  ["M4", "#f5a97f", "#ffd9b8"], ["M5", "#f8d8b0", "#fff3e0"],
  ["M6", "#e88a6b", "#f7c59f"], ["M7", "#a8c5f0", "#dbe8ff"],
];

const EMOTIONS = ["Happy", "Sad", "Angry", "Surprised", "Shy"];

export default function EnhanceTab({ source, armed, onOpenFilters }) {
  const [presets, setPresets] = useState(null);   // null = loading; [] = load failed
  const [lines, openLine] = useResultLines();
  const [busyKey, setBusyKey] = useState("");
  const [emo, setEmo] = useState("Happy");
  const busyRef = useRef(false);

  // Price only when armed (the fetch needs the mirror). Parallelized + cached server-side, so
  // this lands in ~1s and the tiles are already on screen from SKELETON meanwhile.
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

  const costLabel = (p) =>
    p.free_card ? "✦ free card"
      : p.price != null ? "◆ " + Number(p.price).toLocaleString()
        : "spends";

  const run = async (p) => {
    if (busyRef.current || loading) return;              // needs the priced list (has addressing)
    if (!source) {
      if (window.Toast) {
        window.Toast.show({ kind: "err", title: "Pick a source first",
          msg: "Choose an image in SOURCE above, then run an AI preset on it." });
      }
      return;
    }
    const quote = p.free_card ? "a free card covers it — 0 credits"
      : p.price != null ? "this will spend " + Number(p.price).toLocaleString() + " credits"
        : "this spends credits";
    if (!window.confirm(p.label + " on your source?\n\n" + quote +
        " — AI presets run on the PixAI mirror.")) return;
    busyRef.current = true; setBusyKey(p.key);
    const emit = openLine("Submitting " + p.label + "…");
    const body = p.workflow_name
      ? { source, workflow_name: p.workflow_name }
      : { source, workflow_id: p.workflow_id };
    await submitTask("/api/enhance", body, { label: p.label, emit });
    busyRef.current = false; setBusyKey("");
  };

  return (
    <div className="mgdock-slab mgdock-enhslab" style={{ animationDelay: "40ms" }}>
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
                className={"mgdock-aitile" + (p.has_control ? " ctl" : "") + (busyKey === p.key ? " busy" : "")}
                disabled={loading || !!busyKey}
                onClick={() => run(p)}
                title={loading ? "Pricing…" : source ? p.label : "Pick a source image first"}>
                <span className="mgdock-ainame">{p.label}</span>
                <span className="mgdock-aicostrow">
                  <span className={"mgdock-aicost" + (loading ? " ph" : "")}>{loading ? "◆ ·····" : costLabel(p)}</span>
                  {p.has_control ? <span className="mgdock-aictl">+ control</span> : null}
                </span>
              </button>
            ))}
          </div>

          {/* Change Emotion — thumbnail selector (§3, lines 212-223) */}
          <div className="mgdock-emoctl">
            <div className="mgdock-emolbl">CHANGE EMOTION · thumbnail selector</div>
            <div className="mgdock-emogrid">
              {EMOTIONS.map((e) => (
                <button key={e} type="button"
                  className={"mgdock-emotile" + (emo === e ? " on" : "")}
                  onClick={() => setEmo(e)}>
                  <span className="mgdock-emoslot">{e[0]}</span>
                  <span className="mgdock-emoname">{e}</span>
                </button>
              ))}
            </div>
            <div className="mgdock-emonote">Drop your mascot's emotion set here — or PixAI's preset
              thumbnails. Five shown; the set stays catalog-driven.</div>
          </div>

          <div className="mgdock-enhsecs">Dispatches in <b>seconds</b> — the gate was the
            credential, not the feature.</div>
          <div className="mgdock-enhdiv" />
        </>
      )}

      {/* FREE FILTERS — always (§3 lines 228-234); mirror-independent, offline, no credits */}
      <div className="mgdock-enhsub">FREE FILTERS · offline, no credits</div>
      <div className="mgdock-swgrid">
        {FREE_FILTERS.map(([label, a, b]) => (
          <span key={label} className="mgdock-sw" title={label}
            style={{ background: "linear-gradient(135deg, " + a + ", " + b + ")" }} />
        ))}
      </div>
      <button type="button" className="mgdock-enhcompare" onClick={onOpenFilters}>◐ Open compare view — M1–M7</button>

      {armed && !source ? (
        <div className="mgdock-enhpick">Pick a source image in SOURCE above, then tap a preset to run it.</div>
      ) : null}
      <ResultLines lines={lines} />
    </div>
  );
}

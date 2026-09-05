import React, { useEffect, useRef, useState } from "react";
import { submitTask, useResultLines } from "../gen/submitTask.js";
import { ResultLines } from "./EditTab.jsx";
import { groupFamilies } from "../gen/emotionFamilies.js";
import { apiGet } from "../api.js";

/* The Enhance sub-tab, rebuilt to `moonglade-internal/design/enhance/Enhance Family
   Handoff.dc.html` comps A2 (drawer) and A3 (Change Emotion), picks 1c / 1f, committed
   2026-09-04. Issues #48 (the drawer was one tall column beside an empty third slab),
   #44 (the "Dispatches in seconds" sentence came apart) and #49 (~35 emotion tiles in one
   scrolling wall).

   WHAT CHANGED, and what didn't:
     LAYOUT (#48)  The sub-tab is TWO slabs now, not one: this file's main slab (header ·
                   preset grid 3-up · the emotion picker) takes the wide left column, and
                   .mgdock-enhside takes the narrow right one UNDER the shared SOURCE slab,
                   with the Generate CTA pinned to its bottom. dock.css's
                   .mgdock-editslabs.enh does the placing; the drawer sets that class only
                   while the mirror is armed, since unarmed there are no presets to balance.
     SENTENCE (#44) It was `Dispatches in <b>seconds</b> — …` inside .mgdock-enhsecs, which
                   was `display: flex` -- so the three text runs became three FLEX ITEMS and
                   the sentence shattered into pieces with the spacing wrong. It is one
                   inline text node in one <span> beside the header now, exactly as the comp
                   draws it (comp A2 line 115), and the emerald reassurance box is gone with
                   the flex container that broke it.
     FILTERS       The inline 12-swatch teaser strip and "◐ Open compare view — M1–M7" are
                   RETIRED. One door: "Open the Darkroom ▸" (comp A2 line 129) opens the
                   full-screen room (Darkroom.jsx).
     EMOTIONS (#49) Five family tabs, one family on screen, 4 across, no scrolling. The
                   mapping is DATA (gen/emotionFamilies.js) and an unmapped expression lands
                   in a visible "More" tab rather than disappearing.
     UNCHANGED     The presets, their live pricing (/api/enhance/presets), the confirm, the
                   submit body and the mirror gate are all exactly as they were.

   DIVERGENCE FROM THE COMP, on purpose: comp A2's right column draws a "Strength" slab.
   Enhance presets have no strength knob -- /api/enhance takes {source, workflow, emotion?}
   and nothing else -- and this drawer already refuses to draw controls that change nothing
   (the QUALITY slab's no-knob line, owner ruling 2026-08-16). The comp's Strength slab is
   the Edit stack's, and the Edit stack is what the right column actually holds. */

// Real preset thumbnails, packaged like every other branding-class asset in this app: NOT
// committed to the repo -- they live in the shipped asset container (moonglade.dat) as
// bridge/preset_*.webp, resolved loose-then-container and served via /branding/<path>. On a box
// without the container (or a fresh install before its download), the route 404s and onError
// hides the <img> so the tile still reads (initial + name + cost), matching the branding contract.
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

export default function EnhanceTab({ source, armed, onOpenFilters }) {
  const [presets, setPresets] = useState(null);   // null = loading; [] = load failed
  const [sel, setSel] = useState("handfix");       // Handfix selected by default, like the real surface
  const [lines, openLine] = useResultLines();
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [emotions, setEmotions] = useState(null);   // Change Emotion options; null = not loaded
  const [emotionKey, setEmotionKey] = useState("");
  const [fam, setFam] = useState(0);                // which family tab is up

  useEffect(() => {
    if (!armed) { setPresets(null); return undefined; }
    let live = true;
    apiGet("/api/enhance/presets")
      .then((d) => { if (live) setPresets((d && d.presets) || []); });
    return () => { live = false; };
  }, [armed]);

  // Lazily load the staged Change-Emotion options the first time that preset is opened.
  useEffect(() => {
    if (!armed || sel !== "emotion" || emotions !== null) return undefined;
    let live = true;
    apiGet("/api/enhance/emotions")
      .then((d) => { if (live) setEmotions((d && d.emotions) || []); });
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

  // The family tabs render from the LIVE staged list, so an expression this build has never
  // heard of shows up under "More" instead of being silently absent (handoff A3).
  const fams = groupFamilies(emotions);
  const famIdx = Math.min(fam, Math.max(0, fams.length - 1));
  const openFam = fams[famIdx] || null;
  const staged = Array.isArray(emotions) ? emotions.length : 0;

  // Not armed: no presets exist to lay out (the Bridge's §2 OFF rule), so the sub-tab is one
  // quiet slab whose only door is the Darkroom.
  if (!armed) {
    return (
      <div className="mgdock-slab mgdock-enhslab">
        <div className="mgdock-enhhead">
          <span className="mgdock-enhtitle">AI Enhance</span>
          <span className="mgdock-enhline">Turn on Mirror to PixAI (Control Panel → Maintenance) for the one-click presets. The art filters never needed it.</span>
        </div>
        <button type="button" className="mgdock-darkroom" onClick={onOpenFilters}>
          <span>Free art filters</span><span className="go">Open the Darkroom ▸</span>
        </button>
      </div>
    );
  }

  return (
    <>
      <div className="mgdock-slab mgdock-enhslab">
        {/* comp A2 113-116. The sentence is ONE text node in ONE span: the header row is a
            flex row, but nothing inside the sentence is a flex item, which is the whole of
            #44. Do not wrap a word of it in <b>. */}
        <div className="mgdock-enhhead">
          <span className="mgdock-enhtitle">AI Enhance</span>
          <span className="mgdock-enhline">Dispatches in seconds — the mirror does the waiting, your gallery gets the result.</span>
          <span className="sp" />
          <span className="mgdock-enhmirror">● runs on the mirror</span>
        </div>

        {/* the preset grid, 3-up (comp A2 118-125) */}
        <div className="mgdock-aigrid">
          {rows.map((p) => (
            <button key={p.key} type="button"
              className={"mgdock-aitile" + (sel === p.key ? " on" : "")}
              onClick={() => setSel(p.key)} title={p.label}>
              <span className="mgdock-aiart">
                <span className="mgdock-aiinit" aria-hidden="true">{p.label[0]}</span>
                <img className="mgdock-aithumb" src={THUMB[p.key]} alt="" loading="lazy"
                  onError={(e) => { e.currentTarget.style.display = "none"; }} />
              </span>
              <span className="mgdock-aimeta">
                <span className="mgdock-ainame">{p.label}</span>
                <span className={"mgdock-aicost" + (loading ? " ph" : "")}>{loading ? "◆ ·····" : cost(p)}</span>
              </span>
            </button>
          ))}
        </div>

        {/* CHANGE EMOTION (comp A3): family tabs, one family on screen, 4 across. */}
        {sel === "emotion" && (
          <div className="mgdock-emopick">
            <div className="mgdock-enhsub">TARGET EXPRESSION</div>
            {emotions === null ? (
              <div className="mgdock-enhnote">Loading expressions…</div>
            ) : emotions.length === 0 ? (
              <div className="mgdock-enhnote">No expression art staged yet — expression
                thumbnails ship in the app&apos;s asset bundle.</div>
            ) : (
              <>
                <div className="mgdock-emotabs" role="tablist">
                  {fams.map((f, i) => (
                    <button key={f.id} type="button" role="tab" aria-selected={i === famIdx}
                      className={"mgdock-emotab" + (i === famIdx ? " on" : "")}
                      title={f.id === "more"
                        ? "Expressions this build has no family for — never dropped, always listed"
                        : f.label}
                      onClick={() => setFam(i)}>{f.label}</button>
                  ))}
                </div>
                <div className="mgdock-emogrid">
                  {openFam && openFam.items.map((e) => (
                    <button key={e.key} type="button"
                      className={"mgdock-emotile" + (emotionKey === e.key ? " on" : "")}
                      onClick={() => setEmotionKey(e.key)}
                      title={e.membership ? e.label + " — needs a PixAI membership" : e.label}>
                      {/* the family colour is a GLYPH TINT: the tile itself stays neutral */}
                      <span className="mgdock-emoglyph" style={{ color: openFam.color }}
                        aria-hidden="true">{openFam.glyph}</span>
                      <span className="mgdock-emoname">{e.label}</span>
                      {e.membership && <span className="mgdock-aigate" title="Membership required">★</span>}
                    </button>
                  ))}
                </div>
                <div className="mgdock-emocount">
                  {openFam ? openFam.items.length : 0} of {staged} · the others live in the other families
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* The right column's lower half (comp A2 129-130): the one door to the Darkroom, and
          the Generate CTA pinned to the bottom so it lines up with the preset grid's foot. */}
      <div className="mgdock-slab mgdock-enhside">
        <button type="button" className="mgdock-darkroom" onClick={onOpenFilters}>
          <span>Free art filters</span><span className="go">Open the Darkroom ▸</span>
        </button>
        <ResultLines lines={lines} />
        <button type="button" className={"mgdock-enhgen" + (genOff ? " off" : "")} disabled={genOff}
          title={!source ? "Add a source image in SOURCE above"
            : needEmotion ? "Pick a target expression first"
              : loading ? "Pricing…" : "Generate " + selRow.label + " — runs on the mirror"}
          onClick={run}>
          <span>&#10022; Enhance {selRow ? selRow.label : ""}</span>
          <span className="mgdock-enhgencost">{loading ? "…" : cost(priced)}</span>
        </button>
      </div>
    </>
  );
}

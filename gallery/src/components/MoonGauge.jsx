import React from "react";
import { BAR_GEOMETRY, BAR_LEFT, BAR_RAIL, BAR_RIGHT, MOON_FRAMES, MOON_PHASES } from "../art/moonGauge.js";
import { gaugePhase, moonFrame, percentText } from "../lib/moonGaugeCore.js";
import "../styles/moon-gauge.css";

/* MoonGauge -- the one shared progress piece for TRUE fractions (Small Calls handoff, L4 "4a";
   DECISIONS 2026-09-28 "The moon gauge fills only on a true fraction"): a moon whose phase follows
   the fraction, and the BAR9 bar beside it for the exact reading. First used by Session J's
   training strip and runs rows; built so the Folio's ladders and milestones, the Loom's shot
   counts and the phone's pull to refresh mount the same component later.

   Props
     fraction   0..1, or null. Null (not a true fraction -- a generation, an unknown total) draws
                NOTHING: the caller keeps its own text there. Use lib/moonGaugeCore.js's
                fractionOf(done, total) / fractionFromPercent(pct) to get one.
     size       14 | 16 | 18 (px; GAUGE_SIZES names the handoff's four places). Default 16.
     bar        false draws the moon alone (a tight row); default true.
     label      the accessible name ("Nelnamara v3 training"); the value is announced with it.
     className  appended to the root.

   The art (gallery/src/art/moonGauge.js) is the owner's BAR9 sheet, embedded as data URIs so it
   ships in the app build. Its four images are set ONCE as CSS custom properties on :root by the
   rule injected below, not per instance: a Folio page can draw a hundred of these, and a 20 KB
   data URI in every element's style attribute is exactly the bloat that avoids.

   Phase: 0 is a new-moon outline, 1 a full moon with a lavender glow that breathes (a steady
   glow under reduced motion); in between, the nearest of the art's 17 frames (one per 6.25 %). */

let injected = false;
function injectArt() {
  if (injected || typeof document === "undefined") return;
  injected = true;
  const el = document.createElement("style");
  el.setAttribute("data-mg", "moon-gauge-art");
  el.textContent = ":root{"
    + "--mgm-phases:url(" + MOON_PHASES + ");"
    + "--mgm-left:url(" + BAR_LEFT + ");"
    + "--mgm-rail:url(" + BAR_RAIL + ");"
    + "--mgm-right:url(" + BAR_RIGHT + ");"
    + "--mgm-frames:" + MOON_FRAMES + ";"
    + "--mgm-rail-top:" + BAR_GEOMETRY.railTop + ";"
    + "--mgm-rail-h:" + BAR_GEOMETRY.railHeight + ";"
    + "--mgm-chan-top:" + (BAR_GEOMETRY.channelTop * 100) + "%;"
    + "--mgm-chan-h:" + (BAR_GEOMETRY.channelHeight * 100) + "%;"
    + "--mgm-left-ar:" + BAR_GEOMETRY.leftAspect + ";"
    + "--mgm-right-ar:" + BAR_GEOMETRY.rightAspect + ";}";
  document.head.appendChild(el);
}

export default function MoonGauge({ fraction, size = 16, bar = true, label = "", className = "" }) {
  if (typeof fraction !== "number" || !Number.isFinite(fraction)) return null;
  injectArt();
  const f = Math.min(1, Math.max(0, fraction));
  const frame = moonFrame(f, MOON_FRAMES);
  const phase = gaugePhase(f);
  const pct = percentText(f);
  return (
    <span className={"mgm" + (className ? " " + className : "")} data-phase={phase}
      style={{ "--mgm-s": size + "px", "--mgm-frame": frame }}
      role="progressbar" aria-valuemin={0} aria-valuemax={100}
      aria-valuenow={Math.round(f * 100)} aria-valuetext={pct}
      aria-label={label || undefined}>
      <span className="mgm-moon" aria-hidden="true" />
      {bar && (
        <span className="mgm-bar" aria-hidden="true">
          <span className="mgm-cap l" />
          <span className="mgm-rail"><span className="mgm-fill" style={{ width: (f * 100) + "%" }} /></span>
          <span className="mgm-cap r" />
        </span>
      )}
    </span>
  );
}

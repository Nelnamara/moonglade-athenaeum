import React from "react";
import MoonGauge from "../MoonGauge.jsx";
import { fractionFromPercent, GAUGE_SIZES } from "../../lib/moonGaugeCore.js";
import { etaLeftText } from "../../gen/trainCore.js";

/* The pinned "now training" strip (Training Handoff 5c): the newest running job -- queued or
   training -- on the chooser and on Runs; "+N more" when there are several; gone when nothing
   runs. The moon gauge (L4) shows only when PixAI reports a percentage: a queued run has none,
   so it gets its words and no gauge.

   Two drawings, both the handoff's: the chooser's (A) is one line -- name · state, the gauge,
   the reading, View › -- and Runs' (E) leads with the run's cover and puts the gauge under the
   name. `onView` is the chooser's way to Runs; Runs passes none. */
export default function TrainStrip({ running, onView, size = GAUGE_SIZES.strip, withCover = false,
  className = "" }) {
  const list = running || [];
  if (!list.length) return null;
  const r = list[0];
  const f = r.status === "running" ? fractionFromPercent(r.progress) : null;
  const left = etaLeftText(r.eta_left_ms);
  const reading = r.status === "waiting" ? "queued"
    : f !== null ? Math.floor(f * 100) + "%" + (left ? " · " + left : "") : "training";
  const name = (
    <div className="mgtr-strip-name">
      {r.title} · {r.status === "waiting" ? "queued" : "training"}
      {list.length > 1 && <span className="mgtr-strip-more"> · +{list.length - 1} more</span>}
    </div>
  );
  const gauge = f !== null && (
    <MoonGauge fraction={f} size={size} className="mgtr-strip-gauge"
      label={r.title + " training progress"} />
  );
  return (
    <div className={"mgtr-strip" + (withCover ? " covered" : "") + (className ? " " + className : "")}
      role="status">
      {withCover && (r.cover ? <img className="mgtr-strip-cover" src={r.cover} alt="" />
        : <span className="mgtr-strip-cover" />)}
      {withCover ? <div className="mgtr-strip-text">{name}{gauge}</div> : <>{name}{gauge}</>}
      <div className="mgtr-strip-read">{reading}</div>
      {onView && (
        <button type="button" className="mgtr-strip-view" onClick={onView}>View ›</button>
      )}
    </div>
  );
}

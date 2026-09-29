import React from "react";
import TrainStrip from "./TrainStrip.jsx";
import { runsSummary } from "../../gen/trainCore.js";

/* The chooser the overlay opens on (Training Handoff A / decision 1a): the pinned strip while
   something trains, the Basic and Advanced cards (step chips, two bullets, the time), and the
   Runs row. Only reads; each card and the row is a press into its screen.

   The Advanced card's second bullet is corrected by the owner's 2026-09-28 capture (BUILD
   section 5): PixAI locks the parameters at its defaults today, so the card does not promise
   they can be adjusted -- it says they are shown, at PixAI's defaults. */
const MODES = [
  { key: "basic", title: "Basic training", first: true,
    body: "Pick what you're training, add your images, and start. We take care of the rest.",
    steps: ["Choose a goal", "Add images", "Review and start"],
    bullets: ["Training settings chosen automatically", "Images described automatically"],
    time: "About 30 minutes" },
  { key: "advanced", title: "Advanced training", first: false,
    body: "Check the description on every image and see the training parameters before you start.",
    steps: ["Set up", "Descriptions", "Parameters", "Start"],
    bullets: ["Edit the description on each image", "Length, learning rate and detail capacity, at PixAI's defaults for now"],
    time: "About 1 to 2 hours" },
];

export default function TrainChooser({ runs, onPick, onRuns, paused, resumesAt }) {
  const summary = runsSummary(runs.runs);
  return (
    <div className="mgtr-chooser">
      <TrainStrip running={runs.running} onView={onRuns} />
      {paused && (
        <div className="mgtr-warnnote">PixAI has paused new training runs{resumesAt ? " until about " + resumesAt : ""}. Runs already training carry on.</div>
      )}
      <div className="mgtr-modes">
        {MODES.map((m) => (
          <button type="button" key={m.key} className="mgtr-mode" onClick={() => onPick(m.key)}>
            <span className="mgtr-mode-head">
              <span className="mgtr-mode-title">{m.title}</span>
              {m.first && <span className="mgtr-mode-first">Good for your first LoRA</span>}
            </span>
            <span className="mgtr-mode-body">{m.body}</span>
            <span className="mgtr-mode-steps">
              {m.steps.map((s) => <span key={s} className="mgtr-mode-step">{s}</span>)}
            </span>
            {m.bullets.map((b) => <span key={b} className="mgtr-mode-bullet">· {b}</span>)}
            <span className="mgtr-mode-time">{m.time} →</span>
          </button>
        ))}
      </div>
      <button type="button" className="mgtr-runsrow" onClick={onRuns}>
        <span className="mgtr-runsrow-text">
          <span className="mgtr-runsrow-title">Runs</span>
          <span className="mgtr-runsrow-sub">
            Progress, drafts to continue, finished LoRAs to publish{summary ? " · " + summary : ""}
          </span>
        </span>
        <span className="mgtr-runsrow-go" aria-hidden="true">›</span>
      </button>
    </div>
  );
}

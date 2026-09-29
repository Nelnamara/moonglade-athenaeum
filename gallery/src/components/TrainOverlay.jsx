import React, { useState } from "react";
import "../styles/overlays.css";
import "../styles/train.css";
import useScrollLock from "../hooks/useScrollLock.js";
import { loraForDock } from "../gen/trainCore.js";
import {
  useBasicTraining, useCsrf, usePublish, useRetry, useTrainRuns, useTrainSetup,
} from "./train/useTraining.js";
import TrainChooser from "./train/TrainChooser.jsx";
import TrainBasic from "./train/TrainBasic.jsx";
import TrainStrip from "./train/TrainStrip.jsx";
import RunsList, { RetryConfirm } from "./train/RunsList.jsx";
import PublishSheet from "./train/PublishSheet.jsx";

/* ⚗ Train a LoRA, desktop -- Session J (Training Handoff.dc.html, committed 2026-09-28; picks
   1a · 2a · 4a · 5c · 6a, with the owner's 2026-09-28 corrections in
   moonglade-internal/design/notes/training/BUILD-w3-train.md section 5). It replaces the old
   one-page ovTrain body; the mount (App.jsx, overlay === "train"), the way it opens (the nav's
   Train) and the z-order (the shared .mgv-scrim / .mgv-host, 410/411 in the 300-500 overlay
   band) are unchanged.

   Screens: the CHOOSER it opens on (Basic / Advanced cards, the Runs row, the pinned strip
   while something trains) -> BASIC (three steps) or ADVANCED (Stage B builds its wizard; the
   card is here and leads to a placeholder until then) -> RUNS (filters, one row per run, one
   action each), with the PUBLISH sheet and the RETRY confirm laid over it.

   NOTHING WRITES ON OPEN (DECISIONS 2026-09-28). Opening reads the training config, the free
   trainings and the runs list; every write is a press, and every paid or irreversible press
   shows the QUOTED amount it will send and asks once (useTraining.js carries the calls; the
   server re-checks everything, BUILD sections 3 and 7).

   The runs list polls every 15 s only while something is queued, training or being described,
   and only while a screen that shows it -- the chooser or Runs -- is open (useTrainRuns). */
export default function TrainOverlay({ onClose, onUseLora }) {
  useScrollLock();
  const csrf = useCsrf();
  const setup = useTrainSetup();
  const [view, setView] = useState("chooser");       // chooser | basic | advanced | runs
  const [basicStep, setBasicStep] = useState(1);
  const [draftId, setDraftId] = useState("");
  const [filter, setFilter] = useState("all");
  const runs = useTrainRuns({ enabled: view === "chooser" || view === "runs" });
  const basic = useBasicTraining(setup, csrf);
  const retry = useRetry(csrf, () => runs.refresh());
  const pub = usePublish(csrf, () => runs.refresh());

  const toRuns = () => { setView("runs"); };
  const onAction = (kind, row) => {
    if (kind === "continue") { setDraftId(row.id); setView("advanced"); }
    else if (kind === "publish") pub.open("publish", row);
    else if (kind === "make-public") pub.open("make-public", row);
    else if (kind === "retry") retry.preview(row);
    else if (kind === "use") {
      const lora = loraForDock(row, setup.archOf);
      if (lora && onUseLora) onUseLora(lora);
    }
  };

  const head = view === "runs" ? (
    <div className="mgtr-head runs">
      <button type="button" className="mgtr-back" onClick={() => setView("chooser")}>‹ Train a LoRA</button>
      <div className="mgtr-head-title">Runs</div>
      <button type="button" className="mgtr-newbtn" onClick={() => setView("chooser")}>+ New training</button>
      <button type="button" className="mgv-x" onClick={onClose} aria-label="Close">×</button>
    </div>
  ) : (
    <div className="mgtr-head">
      <div className="mgtr-head-title">⚗ Train a LoRA</div>
      <div className="mgtr-sub">runs on PixAI; the library keeps the receipts</div>
      <button type="button" className="mgv-x" onClick={onClose} aria-label="Close">×</button>
    </div>
  );

  return (
    <>
      <div className="mgv-scrim" onClick={onClose} />
      <div className="mgv-host">
        <div className={"mgtr-slab" + (view === "basic" || view === "advanced" ? " wiz" : "")}
          role="dialog" aria-label="Train a LoRA" data-view={view}>
          {head}
          <div className="mgtr-scroll">
            {view === "chooser" && (
              <TrainChooser runs={runs} paused={setup.paused} resumesAt={setup.resumesAt}
                onRuns={toRuns}
                onPick={(k) => { if (k === "advanced") setDraftId(""); setView(k); }} />
            )}
            {view === "basic" && (
              <TrainBasic b={basic} setup={setup} step={basicStep} setStep={setBasicStep}
                onBack={() => setView("chooser")} onRuns={toRuns}
                onAdvanced={() => { setDraftId(""); setView("advanced"); }} />
            )}
            {view === "advanced" && (
              <div className="mgtr-wiz">
                <div className="mgtr-wizhead">
                  <button type="button" className="mgtr-back" onClick={() => setView(draftId ? "runs" : "chooser")}>‹ Back</button>
                  <span className="mgtr-badge">Advanced training</span>
                </div>
                <div className="mgtr-card mgtr-soon">
                  <div className="mgtr-h">Advanced training arrives in the next commit.</div>
                  <div className="mgtr-note">
                    {draftId ? "This draft will open here at the step it stopped at. Nothing has been changed on it."
                      : "Set up, descriptions, parameters and start will be here. Nothing has been sent to PixAI."}
                  </div>
                  <button type="button" className="mgtr-across left" onClick={() => setView("basic")}>Use Basic instead</button>
                </div>
              </div>
            )}
            {view === "runs" && (
              <div className="mgtr-runsview">
                <TrainStrip running={runs.running} withCover />
                {retry.err && !retry.ask && <div className="mgtr-err">⚠ {retry.err}</div>}
                {runs.errors && runs.errors.length > 0 && (
                  <div className="mgtr-warnnote">Some runs couldn't be read just now: {runs.errors.join(" · ")}</div>
                )}
                {!runs.loaded ? <div className="mgtr-dim mgtr-runs-empty">Reading your runs…</div>
                  : <RunsList runs={runs.runs} filter={filter} setFilter={setFilter} onAction={onAction} />}
              </div>
            )}
          </div>
          {retry.ask && (
            <div className="mgtr-layer">
              <div className="mgtr-layer-scrim" onClick={() => { if (!retry.busy) retry.setAsk(null); }} />
              <div className="mgtr-sheet" role="dialog" aria-label="Retry">
                <RetryConfirm retry={retry} />
              </div>
            </div>
          )}
          <PublishSheet pub={pub} />
        </div>
      </div>
    </>
  );
}

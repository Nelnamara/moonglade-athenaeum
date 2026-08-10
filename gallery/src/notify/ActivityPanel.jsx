import React from "react";
import ActivityRow from "./ActivityRow.jsx";

/* ActivityPanel -- the anchored dropdown body (Claude Design handoff 2026-08-09, drift item
   39): opens directly under its host's trigger chip, not centered/floating elsewhere.
   Collapses via the host's own "closing" transition class (each host drives its own
   mount/unmount timing to match its surface's existing collapse choreography -- see
   ActivityChip's caller in SeparatorBar.jsx / the Loom toolbar / AppMobile's sheet). */

export default function ActivityPanel({
  jobs, expandedId, onToggleRow, onDismiss, onClearFinished, onClose, compact, className, closing,
  edge, onSetEdge,
}) {
  return (
    <div className={"at-panel" + (edge === "left" ? " edge-left" : "") + (closing ? " closing" : "") + (className ? " " + className : "")}>
      <div className="at-head">
        <span className="at-title">Activity</span>
        {jobs.length ? <span className="at-count">{jobs.length}</span> : null}
        <div className="at-headsp" />
        {jobs.length ? (
          <span className="at-clear" role="button" tabIndex={0}
            onClick={onClearFinished}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClearFinished(); } }}>
            clear finished
          </span>
        ) : null}
        {onSetEdge ? (
          <div className="at-edgeseg" role="group" aria-label="Dock the Activity panel left or right">
            <button type="button" className={"at-edgebtn" + (edge === "left" ? " on" : "")}
              title="Dock to the left" onClick={() => onSetEdge("left")}>◧</button>
            <button type="button" className={"at-edgebtn" + (edge !== "left" ? " on" : "")}
              title="Dock to the right" onClick={() => onSetEdge("right")}>◨</button>
          </div>
        ) : null}
        <button className="at-collapse" title="Collapse" onClick={onClose}>›</button>
      </div>
      <div className="at-body">
        {!jobs.length ? (
          <div className="at-empty">
            <img className="at-empty-nel" src="/branding/mascots/trk_empty.png" alt="" onError={(e) => e.currentTarget.remove()} />
            <div>The archive is quiet.<br />Generations and syncs will appear here.</div>
          </div>
        ) : jobs.map((j) => (
          <ActivityRow
            key={j.job_id} job={j} compact={compact}
            expanded={expandedId === j.job_id}
            onToggle={onToggleRow} onDismiss={onDismiss}
          />
        ))}
      </div>
    </div>
  );
}

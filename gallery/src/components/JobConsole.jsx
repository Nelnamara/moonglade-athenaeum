import React from "react";
import Icon from "../icons/Icons.jsx";

/* The job console's two shared pieces, used by the Control Panel's Maintenance tab and its Tidy
   tab (One Tidy place, 2026-11-19) -- one job at a time, whichever tab started it. */

/* `locked` (a dedup stage that changes files) draws the lock icon after the words. A missing
   spec draws nothing: summary.actions lists a destructive action only for a session on the
   serving machine, so a LAN session never sees a button the server would refuse. */
export function ActionChip({ spec, dgr, label, armed, onRun, disabled, title, locked }) {
  if (!spec) return null;
  const text = armed ? "Confirm — " + (label || spec.label) : (label || spec.label);
  return (
    <button type="button" className={"mgcp-chip" + (dgr || spec.destructive ? " dgr" : "")}
      onClick={onRun} disabled={disabled} title={title}>
      {text}{locked ? <> <Icon name="lock" /></> : null}
    </button>
  );
}

/* The running job: its name, Stop, the bar, the last lines of its log, and what else waits.
   Control Panel.dc.html:205-210's lockedMinis -- real other-action labels from
   summary.actions (the same list actionSpec() reads), not the design's fixed 3-example array. */
export function JobRunning({ running, progress, log, actions, onStop }) {
  const list = actions || [];
  return (
    <div className="mgcp-running">
      <div className="mgcp-runhead">
        <span className="mgcp-runspin" />
        <b className="mgcp-runname">{running.label}</b>
        <button type="button" className="mgcp-chip dgr" style={{ marginLeft: "auto" }}
          onClick={onStop}>■ Stop this job</button>
      </div>
      <div className="mgcp-runbar">
        <i className={progress?.pct == null ? "indeterminate" : ""}
          style={progress?.pct != null ? { width: progress.pct + "%" } : undefined} />
      </div>
      <div className="mgcp-runlog">
        {log.slice(-6).map((ln, i) => (
          <div key={i} className={ln.indexOf("✓") === 0 ? "ok" : ""}>{ln}</div>
        ))}
      </div>
      <div className="mgcp-lockedrow">
        {list.filter((a) => a.action !== running.action)
          .slice(0, 3).map((a) => (
            <span className="mgcp-lockchip" key={a.action}>{a.label}</span>
          ))}
        {list.length - 1 > 3 && (
          <span className="mgcp-lockchip">
            +{list.length - 1 - 3} more · one job at a time
          </span>
        )}
      </div>
    </div>
  );
}

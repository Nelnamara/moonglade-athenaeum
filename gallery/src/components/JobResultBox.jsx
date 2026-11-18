import React, { useState } from "react";
import Icon from "../icons/Icons.jsx";

// The Control Panel's finished-job box, shared by the desktop panel and the phone's Control tab.
// A Dedup stage (jobResult.dedup, lib/dedupResult.js) leads with its one plain sentence and folds
// the file lines under "Show the N files"; every other job keeps its tail of log lines.
export default function JobResultBox({ jobResult, onDismiss }) {
  const [open, setOpen] = useState(false);
  const dedup = jobResult.dedup;
  return (
    <div className={"mgcp-runresult" + (jobResult.ok ? "" : " warn")}>
      <div className="mgcp-runresulthead">
        {dedup
          ? <>{jobResult.ok ? "✓" : <Icon name="warning" />} <span className="mgcp-runsentence">{dedup.sentence}</span></>
          : jobResult.ok ? "✓ Finished"
            : <><Icon name="warning" /> {"Finished with " + jobResult.warnCount + " warning" + (jobResult.warnCount !== 1 ? "s" : "")}</>}
        <button type="button" className="mgcp-run" onClick={onDismiss}>dismiss</button>
      </div>
      {dedup && dedup.files.length > 0 && (
        <>
          <button type="button" className="mgcp-runfold" aria-expanded={open}
            onClick={() => setOpen(!open)}>
            {open ? "Hide the " : "Show the "}{dedup.count}{" file" + (dedup.count === "1" ? "" : "s")}{" "}
            <span aria-hidden="true">{open ? "⌄" : "›"}</span>
          </button>
          {open && (
            <div className="mgcp-runresultlog mgcp-runfiles">
              {dedup.files.map((ln, i) => <div key={i}>{ln}</div>)}
            </div>
          )}
        </>
      )}
      {!dedup && jobResult.lines.length > 0 && (
        <div className="mgcp-runresultlog">
          {jobResult.lines.map((ln, i) => <div key={i}>{ln}</div>)}
        </div>
      )}
    </div>
  );
}

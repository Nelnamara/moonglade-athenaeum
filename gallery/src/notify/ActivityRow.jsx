import React, { useEffect, useState } from "react";
import { ago, fmtClock, fmtDuration, groupThousands, kindLabel, labelFor } from "./format.js";

/* ActivityRow -- one job row inside the new header-docked Activity dropdown (Claude Design
   handoff 2026-08-09, drift item 39: "Click a row to expand inline STATUS / MODEL / COST /
   TASK id (+ copy)... no dead-end rows"). Row anatomy is unchanged from the old floating
   tray's <Row> (icon left / label+sub middle / thumbnail right) -- what changed is WHERE the
   detail lives: inline under the row on click, replacing the old #jt-detail floating popover
   entirely (no more anchor-position math, no more click-outside-to-close listener).

   MODEL row deliberately omitted here, unlike the design's mockup: a real generation job's
   /api/jobs record carries no model/base field today (notify/jobs.js's register() only ever
   POSTs {job_id, type, label, status, count}) -- inventing one would mean fabricating data
   that was never sent, the exact thing this app's Cost/ETA rows already refuse to do
   (typeof+isFinite checks, "an unknown cost shows NO row at all"). Same rule applied here:
   no field, no row. Wiring real per-job model tracking is a separate, later enhancement. */

export default function ActivityRow({ job: j, expanded, onToggle, onDismiss, compact }) {
  const st = j.status || "running";
  // `started` is ABSENT on non-PixAI jobs and pre-feature rows -- absent means UNKNOWN, which
  // keeps the plain spinner. `=== false`, never `!j.started` (a truthiness check would brand
  // every panel/cli/delete/import job, which never carries this field, as queued).
  const queued = st === "running" && j.started === false;
  const fin = st === "done" || st === "failed" || st === "done_with_errors" || st === "stale";
  const mid = (j.media_ids || [])[0] || "";
  const pct = (st === "running" && j.total)
    ? Math.min(100, Math.round((j.done || 0) / j.total * 100)) : null;
  const showErr = (st === "failed" || st === "done_with_errors" || st === "stale") && j.error;
  const cls = st === "failed" ? " at-failed"
    : (st === "done_with_errors" || st === "stale") ? " at-warn" : "";

  const icon = st === "done" ? (
    <><span className="at-ok at-glyph">✓</span><img className="at-nel" src="/branding/mascots/trk_done.png" alt="" onError={(e) => e.currentTarget.remove()} /></>
  ) : st === "done_with_errors" ? (
    <><span className="at-warn at-glyph">⚠</span><img className="at-nel" src="/branding/mascots/trk_done.png" alt="" onError={(e) => e.currentTarget.remove()} /></>
  ) : st === "failed" ? (
    <><span className="at-err at-glyph">⚠</span><img className="at-nel" src="/branding/mascots/trk_fail.png" alt="" onError={(e) => e.currentTarget.remove()} /></>
  ) : st === "stale" ? (
    <><span className="at-warn at-glyph">?</span><img className="at-nel" src="/branding/mascots/trk_fail.png" alt="" onError={(e) => e.currentTarget.remove()} /></>
  ) : (
    <span className={"at-spin" + (queued ? " at-queued" : "")}>
      <img className="at-nel" src="/branding/nel_spinner.png" alt="" onError={(e) => e.currentTarget.remove()} />
      <i className="at-ring" />
    </span>
  );

  // The live SPENT clock (M25, carried over from the old floating #jt-detail popover): only
  // needed while the inline detail is actually visible AND the job is still running -- gated
  // on [running, expanded] rather than always-on, so a poll's own 2.5-7s cadence isn't the
  // only thing making "so far" tick up, but a collapsed or finished row starts/keeps no timer.
  // Terminal-ness is DERIVED (`running`), never a hardcoded status list -- the exact discipline
  // that caused M25 the first time (a finished job's clock outliving it and overwriting the
  // real final duration with a climbing "so far" figure). Declared before `running` itself (not
  // after) so it stays OUTSIDE the running/effect block a test harness extracts to re-run in
  // isolation -- see med-mg-notify-detail-tick.test.js.
  const [, tick] = useState(0);
  const running = st === "running";
  const startedAt = j.started_at || j.ts || 0;
  const spent = (running ? (Date.now() / 1000) : (j.ts || startedAt)) - startedAt;
  useEffect(() => {
    if (!running || !expanded) return undefined;
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [running, expanded]);

  const [copied, setCopied] = React.useState(false);
  const copy = (e) => {
    e.stopPropagation();
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(j.job_id || "").catch(() => {});
      }
    } catch { /* silent no-op, per spec */ }
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };

  const stopTracking = (e) => {
    e.stopPropagation();
    if (!fin && !window.confirm(
      "Stop tracking this job?\n\nThis does NOT cancel it on PixAI or touch your credits -- it "
      + "only stops your local Job Tracker from watching it. If it was actually still "
      + "generating, the finished image will still land in your library later; it just will "
      + "not be tracked here anymore.",
    )) return;
    onDismiss(j.job_id);
  };

  return (
    <div
      className={"at-row" + cls + (expanded ? " open" : "")} tabIndex={0} role="button" aria-expanded={expanded}
      onClick={() => onToggle(j.job_id)}
      onKeyDown={(e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        onToggle(j.job_id);
      }}
    >
      <div className="at-line">
        <div className="at-ic">{icon}</div>
        <div className="at-main">
          <div className="at-lab">{labelFor(j, fin)}</div>
          <div className="at-sub">
            <span className="at-kind">{kindLabel(j.type)}</span>
            {queued ? (
              <span className="at-phase" title="PixAI has accepted this generation and no worker has picked it up yet — it has not started rendering.">queued</span>
            ) : null}
            {queued && typeof j.eta_seconds === "number" && isFinite(j.eta_seconds) ? (
              <span className="at-eta" title="The queue wait PixAI predicted for this model when the job was accepted. An estimate of the WAIT, not a countdown, and not progress — PixAI reports no progress on a running task.">
                est. {fmtDuration(j.eta_seconds)} wait
              </span>
            ) : null}
            <span className="at-when">{ago(j.ts)}</span>
          </div>
        </div>
        {st === "done" && mid ? (
          <a className="at-thumb" href={"/?image=" + encodeURIComponent(mid)}
            onClick={(e) => {
              e.stopPropagation();
              if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;   // real new-tab open
              e.preventDefault();
              document.dispatchEvent(new CustomEvent("mg-open-details", { bubbles: true, composed: true, detail: { mid } }));
            }}>
            <img src={"/thumbs/" + encodeURIComponent(mid) + ".jpg"} alt="" />
          </a>
        ) : null}
      </div>
      {pct != null ? <div className="at-bar"><i style={{ width: pct + "%" }} /></div> : null}
      {showErr ? <div className="at-errmsg">{j.error}</div> : null}
      {expanded ? (
        <div className="at-detail">
          <div className="at-drow">
            <span className="at-dk">STATUS</span>
            <span className={"at-dv" + (st === "failed" ? " bad" : (st === "done_with_errors" || st === "stale") ? " warn" : st === "done" ? " good" : "")}>
              {fin ? (st === "done" ? "Done" : st === "failed" ? "Failed" : st === "stale" ? "Stalled" : "Done, with errors") : queued ? "Queued" : "Running"}
            </span>
          </div>
          {typeof j.paid_credit === "number" && isFinite(j.paid_credit) ? (
            <div className="at-drow"><span className="at-dk">COST</span><span className="at-dv">{groupThousands(j.paid_credit)} credits</span></div>
          ) : null}
          <div className="at-drow">
            <span className="at-dk">TASK</span>
            <span className="at-dv at-mono">{j.job_id || "—"}</span>
            <button className={"at-copy" + (copied ? " copied" : "")} title="Copy task ID" onClick={copy}>
              {copied ? "copied!" : "⧉"}
            </button>
          </div>
          {!compact ? (
            <>
              <div className="at-drow at-divider"><span className="at-dk">SENT</span><span className="at-dv at-mono">{fmtClock(startedAt)}</span></div>
              <div className="at-drow"><span className="at-dk">SPENT</span><span className="at-dv at-mono">{fmtDuration(spent)}{running ? " so far" : ""}</span></div>
            </>
          ) : null}
          {typeof j.eta_seconds === "number" && isFinite(j.eta_seconds) ? (
            <div className="at-drow"><span className="at-dk">EST. WAIT</span><span className="at-dv at-mono">{fmtDuration(j.eta_seconds)} (PixAI, when queued)</span></div>
          ) : null}
        </div>
      ) : null}
      {fin ? (
        <button className="at-x" title="Dismiss" onClick={stopTracking}>×</button>
      ) : (
        <button className="at-x at-forcex" title="Stop tracking this job -- does not cancel it on PixAI" onClick={stopTracking}>Stop tracking</button>
      )}
    </div>
  );
}

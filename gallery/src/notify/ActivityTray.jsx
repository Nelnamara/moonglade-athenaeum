import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  subscribe, openTray, closeTray, dismiss, clearFinished, runningCount,
} from "./jobsStore.js";
import { ago, fmtClock, fmtDuration, groupThousands, kindLabel, labelFor } from "./format.js";

/* ActivityTray -- the React face of the Job activity tracker (no-vanilla campaign, component
   6): the #jobs-fab pill, the #jobs-tray card, and the #jt-detail popover, all portaled to
   document.body so they stay body-level siblings of #root -- the Loom shell's !important
   z-index/bottom overrides and contact-sheet-overlay.css's hide rule keep targeting the same
   ids they always did. Renders SERVER TRUTH from jobsStore; owns no poll loop of its own.

   The detail popover's live "Time Spent" tick preserves the vanilla's hard-won discipline:
   whether the clock ticks is a fact about the JOB (status === 'running'), re-decided on every
   repaint -- never about the popover merely being open. `stale` is tested by the same direct
   "still running" comparison, so the clock stops for exactly the job most likely to have a
   popover open on it, and starts again if a later server sweep heartbeats it back to running. */

function Row({ j, onDismiss, onOpenDetail }) {
  const st = j.status || "running";
  // `started` is ABSENT on non-PixAI jobs and pre-feature rows -- absent means UNKNOWN, which
  // keeps the plain spinner. `=== false`, never `!j.started`.
  const queued = st === "running" && j.started === false;
  const fin = st === "done" || st === "failed" || st === "done_with_errors" || st === "stale";
  const mid = (j.media_ids || [])[0] || "";
  const pct = (st === "running" && j.total)
    ? Math.min(100, Math.round((j.done || 0) / j.total * 100)) : null;
  const showErr = (st === "failed" || st === "done_with_errors" || st === "stale") && j.error;
  const cls = st === "failed" ? " st-failed"
    : (st === "done_with_errors" || st === "stale") ? " st-warn" : "";

  const icon = st === "done" ? (
    <><span className="jt-ok jt-glyph">✓</span><img className="jt-nel" src="/branding/mascots/trk_done.png" alt="" onError={(e) => e.currentTarget.remove()} /></>
  ) : st === "done_with_errors" ? (
    <><span className="jt-warn jt-glyph">⚠</span><img className="jt-nel" src="/branding/mascots/trk_done.png" alt="" onError={(e) => e.currentTarget.remove()} /></>
  ) : st === "failed" ? (
    <><span className="jt-err jt-glyph">⚠</span><img className="jt-nel" src="/branding/mascots/trk_fail.png" alt="" onError={(e) => e.currentTarget.remove()} /></>
  ) : st === "stale" ? (
    <><span className="jt-warn jt-glyph">?</span><img className="jt-nel" src="/branding/mascots/trk_fail.png" alt="" onError={(e) => e.currentTarget.remove()} /></>
  ) : (
    <span className={"jt-spin" + (queued ? " jt-queued" : "")}>
      <img className="jt-nel" src="/branding/nel_spinner.png" alt="" onError={(e) => e.currentTarget.remove()} />
      <i className="gen-ring" />
    </span>
  );

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
      className={"jt-item" + cls} tabIndex={0} role="button" aria-haspopup="true"
      onClick={(e) => onOpenDetail(j.job_id, e.currentTarget)}
      onKeyDown={(e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        onOpenDetail(j.job_id, e.currentTarget);
      }}
    >
      <div className="jt-ic">{icon}</div>
      <div className="jt-main">
        <div className="jt-lab">{labelFor(j, fin)}</div>
        <div className="jt-sub">
          <span className="jt-kind">{kindLabel(j.type)}</span>
          {queued ? (
            <span className="jt-phase" title="PixAI has accepted this generation and no worker has picked it up yet — it has not started rendering.">queued</span>
          ) : null}
          {queued && typeof j.eta_seconds === "number" && isFinite(j.eta_seconds) ? (
            <span className="jt-eta" title="The queue wait PixAI predicted for this model when the job was accepted. An estimate of the WAIT, not a countdown, and not progress — PixAI reports no progress on a running task.">
              est. {fmtDuration(j.eta_seconds)} wait
            </span>
          ) : null}
          <span className="jt-when">{ago(j.ts)}</span>
        </div>
        {pct != null ? <div className="jt-bar"><i style={{ width: pct + "%" }} /></div> : null}
        {showErr ? <div className="jt-errmsg">{j.error}</div> : null}
      </div>
      {st === "done" && mid ? (
        <a className="jt-thumb" href={"/?image=" + encodeURIComponent(mid)}
          onClick={(e) => {
            e.stopPropagation();
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;   // real new-tab open
            e.preventDefault();
            document.dispatchEvent(new CustomEvent("mg-open-details", { bubbles: true, composed: true, detail: { mid } }));
          }}>
          <img src={"/thumbs/" + encodeURIComponent(mid) + ".jpg"} alt="" />
        </a>
      ) : null}
      {fin ? (
        <button className="jt-x" title="Dismiss" onClick={stopTracking}>×</button>
      ) : (
        <button className="jt-x jt-forcex" title="Stop tracking this job -- does not cancel it on PixAI" onClick={stopTracking}>Stop tracking</button>
      )}
    </div>
  );
}

function Detail({ job, anchor, onClose }) {
  const [, tick] = useState(0);
  const [copied, setCopied] = useState(false);
  const running = (job.status || "running") === "running";
  const startedAt = job.started_at || job.ts || 0;

  // The live clock: an interval only while the JOB is running (re-decided every render).
  useEffect(() => {
    if (!running) return undefined;
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [running]);

  // click-anywhere-else closes; clicks inside the popover or the tray are exempt (a row click
  // must be able to open/switch it without immediately closing what it just opened).
  useEffect(() => {
    const onDoc = (e) => {
      const inDetail = e.target.closest && e.target.closest("#jt-detail");
      const inTray = e.target.closest && e.target.closest("#jobs-tray");
      if (!inDetail && !inTray) onClose();
    };
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("click", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  // Anchor beside the row: prefer the side with room, clamp to the viewport.
  const r = anchor.getBoundingClientRect();
  const w = 264, gap = 10;
  let x = r.right + gap;
  if (x + w > window.innerWidth - 8) x = Math.max(8, r.left - w - gap);
  const y = Math.max(8, Math.min(r.top, window.innerHeight - 140));

  const spent = (running ? (Date.now() / 1000) : (job.ts || startedAt)) - startedAt;
  const copy = () => {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(job.job_id || "").catch(() => {});
      }
    } catch { /* silent no-op, per spec */ }
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };

  return (
    <div id="jt-detail" className="open" aria-hidden="false" style={{ left: x, top: y }}>
      <div className="jd-row">
        <span className="jd-k">Task ID</span>
        <span className="jd-v jd-id">{job.job_id || ""}</span>
        <button className={"jd-copy" + (copied ? " copied" : "")} title="Copy task ID" onClick={copy}>
          {copied ? "copied!" : "copy"}
        </button>
      </div>
      <div className="jd-row"><span className="jd-k">Time Sent</span><span className="jd-v">{fmtClock(startedAt)}</span></div>
      <div className="jd-row">
        <span className="jd-k">Time Spent</span>
        <span className="jd-v">{fmtDuration(spent)}{running ? " so far" : ""}</span>
      </div>
      {typeof job.eta_seconds === "number" && isFinite(job.eta_seconds) ? (
        <div className="jd-row"><span className="jd-k">Est. wait</span><span className="jd-v">{fmtDuration(job.eta_seconds)} (PixAI, when queued)</span></div>
      ) : null}
      {typeof job.paid_credit === "number" && isFinite(job.paid_credit) ? (
        // typeof+isFinite, not truthiness: a card-covered gen genuinely costs 0 and must render
        // "0 credits", while an unknown cost shows NO row at all.
        <div className="jd-row"><span className="jd-k">Cost</span><span className="jd-v">{groupThousands(job.paid_credit)} credits</span></div>
      ) : null}
    </div>
  );
}

export default function ActivityTray() {
  const [state, setState] = useState({ jobs: [], open: false });
  const [detailId, setDetailId] = useState(null);
  const anchorRef = useRef(null);
  useEffect(() => subscribe(setState), []);

  const closeDetail = useCallback(() => { setDetailId(null); anchorRef.current = null; }, []);
  const toggleDetail = useCallback((jid, anchorEl) => {
    setDetailId((cur) => {
      if (cur === jid) { anchorRef.current = null; return null; }
      anchorRef.current = anchorEl;
      return jid;
    });
  }, []);

  const { jobs, open } = state;
  const running = runningCount();
  const detailJob = detailId ? jobs.find((j) => j.job_id === detailId) : null;
  // The job the popover was showing is gone (dismissed/aged out) -> close it.
  useEffect(() => {
    if (detailId && !detailJob) closeDetail();
  }, [detailId, detailJob, closeDetail]);

  return createPortal(
    <>
      <div
        id="jobs-fab" className={(open ? "" : "show") + (running > 0 ? " busy" : "")}
        title="Activity" onClick={() => openTray()}
      >
        <span className="jf-dot" />
        <span id="jobs-fab-badge" className="jf-badge">{running || ""}</span>
        <span>Activity</span>
      </div>
      <div id="jobs-tray" className={open ? "open" : ""} aria-label="Job activity">
        <div className="jt-head">
          <span className="jt-title">◉ Activity{jobs.length ? <span className="jt-count">{jobs.length}</span> : null}</span>
          <button className="jt-hbtn" title="Clear finished" onClick={() => clearFinished()}>clear</button>
          <button className="jt-hbtn" title="Collapse" onClick={() => { closeTray(); closeDetail(); }}>–</button>
        </div>
        <div className="jt-body">
          {!jobs.length ? (
            <div className="jt-empty">
              <img className="jt-empty-nel" src="/branding/mascots/trk_empty.png" alt="" onError={(e) => e.currentTarget.remove()} />
              <div>The archive is quiet.<br />Generations and syncs will appear here.</div>
            </div>
          ) : jobs.map((j) => (
            <Row key={j.job_id} j={j} onDismiss={dismiss} onOpenDetail={toggleDetail} />
          ))}
        </div>
      </div>
      {detailJob && anchorRef.current ? (
        <Detail job={detailJob} anchor={anchorRef.current} onClose={closeDetail} />
      ) : null}
    </>,
    document.body,
  );
}

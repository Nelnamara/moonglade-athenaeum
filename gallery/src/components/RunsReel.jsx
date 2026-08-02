import React, { useState } from "react";

/* The dock's RUNS REEL (design spec C3a) — bound to REAL /api/jobs data, never
   the DC's SEEDED demo runs. The parent (GenerateDrawer) owns the fetch/poll
   and hands the generate-type jobs down; this component only groups + paints.

   Job record fields used (moonglade_backup.read_jobs shape): job_id, status
   ('running' | 'done' | 'failed' | 'done_with_errors' | 'stale'), ts,
   started_at, done, total, media_ids, paid_credit, label, error.

   REUSE GAP (reported, not faked): a job record carries no submit-settings
   snapshot and no existing mechanism prefills the composer from a task id, so
   clicking a done run opens its image (the result-lines' own /full/ pattern)
   instead of the DC's "Use these settings" prefill. */

const TERMINAL = ["done", "failed", "done_with_errors", "stale"];
export const isRunningJob = (j) => TERMINAL.indexOf(j.status || "running") === -1;

/* Live progress: /api/jobs only carries done/total for batch jobs; a PixAI
   generate job has no server-side progress at all (PixAI reports none), so a
   running tile shows the eclipse spinner and only draws the DC's progress
   strip when a real done/total pair exists. */
function pctOf(j) {
  if (!j.total) return null;
  return Math.min(99, Math.round(((j.done || 0) / j.total) * 100));
}

export default function RunsReel({ jobs, historyOpen, reelH }) {
  const [hover, setHover] = useState(null);

  const midnight = new Date();
  midnight.setHours(0, 0, 0, 0);
  const t0 = midnight.getTime() / 1000;

  const today = [], yesterday = [];
  jobs.forEach((j) => {
    const ts = Number(j.started_at || j.ts || 0);
    if (ts >= t0) today.push(j);
    else if (ts >= t0 - 86400) yesterday.push(j);
  });

  const groups = [{ key: "today", label: null, runs: today }];
  if (historyOpen && yesterday.length) {
    groups.push({ key: "yesterday", label: "Yesterday", runs: yesterday });
  }
  const empty = !today.length && (!historyOpen || !yesterday.length);

  const th = Math.max(44, reelH || 132);
  // Aspect-true would need per-run w/h; the job log has none, so every tile
  // takes the DC's fallback ratio (832×1216).
  const tw = Math.max(44, Math.round(th * (832 / 1216)));

  return (
    <div className={"mgdock-reel" + (historyOpen ? " wrap" : "")}>
      {empty && (
        <div className="mgdock-reelempty">
          <div className="mgdock-firstrun" style={{ height: th }}>first run</div>
          <div className="mgdock-emptycopy">
            Runs appear here as they resolve, newest first — they never push the
            composer down, and the reel keeps its own history.
          </div>
        </div>
      )}
      {!empty && groups.map((grp) => (
        <div className="mgdock-reelgrp" key={grp.key}>
          {grp.label && (
            <div className="mgdock-daydiv">
              <i />
              <span>{grp.label}</span>
              <i />
            </div>
          )}
          {grp.runs.map((j) => {
            const running = isRunningJob(j);
            const done = (j.status || "") === "done";
            const failed = !running && !done;
            const mid = (j.media_ids || [])[0] || "";
            const pct = running ? pctOf(j) : null;
            const tag = "#" + String(j.job_id || "").slice(-4);
            const tile = (
              <div
                className={"mgdock-tile" + (done ? " done" : "") + (failed ? " fail" : "")}
                style={{ width: tw, height: th }}
                onMouseEnter={() => setHover(j.job_id)}
                onMouseLeave={() => setHover(null)}
                title={running
                  ? "Generating " + tag + (pct != null ? " · " + pct + "%" : "")
                  : failed
                  ? (j.error || j.status || "failed")
                  : "Open this run's image — reuse-settings isn't wired yet"}
              >
                {done && mid ? (
                  <img className="mgdock-tileimg" src={"/thumbs/" + encodeURIComponent(mid) + ".jpg"} alt="" />
                ) : null}
                {running && (
                  <span className="mgdock-eclipse lg"><span /></span>
                )}
                {running && pct != null && (
                  <div className="mgdock-tilestrip">
                    <div className="mgdock-tiletrack"><i style={{ width: pct + "%" }} /></div>
                    <span>{pct}%</span>
                  </div>
                )}
                {failed && <span className="mgdock-tilefail">⚠</span>}
                {done && mid && (
                  <div className={"mgdock-tilehint" + (hover === j.job_id ? " show" : "")}>
                    <span>Open this run →</span>
                  </div>
                )}
              </div>
            );
            return (
              <div className="mgdock-run" key={j.job_id} style={{ width: tw }}>
                {done && mid ? (
                  <a className="mgdock-tilelink" href={"/full/" + encodeURIComponent(mid)}
                    target="_blank" rel="noreferrer">{tile}</a>
                ) : tile}
                <div className="mgdock-runcap">
                  <span className="mgdock-runtag">{tag}</span>
                  {typeof j.paid_credit === "number" && isFinite(j.paid_credit) ? (
                    j.paid_credit === 0
                      ? <span className="mgdock-runcost free">free card</span>
                      : <span className="mgdock-runcost">~{Math.round(j.paid_credit).toLocaleString()} cr</span>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

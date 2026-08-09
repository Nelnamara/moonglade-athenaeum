import React, { useState } from "react";

/* The dock's RUNS REEL (design spec C3a, Frontend Gallery.dc.html ~1845-2060),
   rebuilt against the real click/prefill/batch behavior spec (2026-08-02) --
   bound to REAL /api/jobs data, never the DC's SEEDED demo runs.

   Job record fields used (moonglade_backup.read_jobs shape): job_id, status
   ('running' | 'done' | 'failed' | 'done_with_errors' | 'stale'), ts,
   started_at, media_ids (list, populated once done), paid_credit, label, error.

   CLICK / REUSE (owner correction, 2026-08-02, binding): a DONE tile's entire
   surface is the reuse trigger -- clicking it PREFILLS the composer with that
   run's settings (never auto-submits; the user reviews then clicks Generate
   themselves). A RUNNING tile has no click action. There is no separate
   "open image" control on a reel tile in this design. The prefill fetch + the
   real composer setters live in GenerateDrawer (onPrefill prop, below).

   PROGRESS: PixAI reports no per-task render progress, so a running tile is a
   generic dim placeholder + an indeterminate spinner -- never a fake percentage
   or a blur-by-percent interpolation against a clock that isn't real.

   BATCH (2026-08-02, closes a verify-flagged gap -- see the report): a real
   PixAI count>1 submission is ONE job with N media_ids, atomic (queued/
   rendered together) -- confirmed via moonglade_gallery.py's
   _log_job(tid, status="done", media_ids=mids). The spec's own porting note
   (generate-runs-spec.md) says the running/done cluster split is a pure render
   decision with no stored flag, and that a batch shows as ONE compact tile
   "sized by how many images were requested, capped visually at 4" while
   running. `count` now rides the submit -> Jobs.track -> Jobs.register chain
   (gen/submitTask.js, static/mg-notify.js) into the job's first log event, so a
   running job with count>1 renders that one reel slot as a mini NxN grid of
   indeterminate placeholders instead of a single spinner. Our atomic job model
   has no "some images done, some still rendering" state the way the DC's
   per-image demo timer did -- the whole job flips running->done at once, and
   at that instant cellsFor already fans it out into N individual, independently
   reusable result tiles. A job whose count never made it into the log (an
   older entry, or a registration path that doesn't know it -- video/Loom/
   classic) falls back to the plain single tile, unchanged. */

const TERMINAL = ["done", "failed", "done_with_errors", "stale"];
export const isRunningJob = (j) => TERMINAL.indexOf(j.status || "running") === -1;

/* Flatten jobs into render CELLS: a running/failed/stale job is one cell; a
   done job fans out into one cell per real media_id (or one empty-result cell
   if PixAI reported done with nothing to show). idx/total ride along so a
   multi-image job's tiles can be told apart without inventing a synthetic
   per-image id the way the DC's batchId scheme did. */
function cellsFor(j) {
  const tag = "#" + String(j.job_id || "").slice(-4);
  if (isRunningJob(j)) {
    // count rides the log's first event only (see the header note) -- absent
    // on anything that didn't know it, which the clamp treats as 1 (plain tile).
    const count = Math.max(1, Math.min(4, Number(j.count) || 1));
    return [{ key: j.job_id, job: j, tag, kind: "running", count }];
  }
  const done = (j.status || "") === "done";
  const mids = done ? (j.media_ids || []) : [];
  if (!mids.length) {
    return [{ key: j.job_id, job: j, tag, kind: done ? "done-empty" : "fail" }];
  }
  return mids.map((mid, i) => ({
    key: j.job_id + ":" + mid, job: j, tag, kind: "done",
    mid, idx: i, total: mids.length,
  }));
}

export default function RunsReel({ jobs, historyOpen, reelH, onPrefill }) {
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
          {grp.runs.flatMap(cellsFor).map((c) => {
            const j = c.job;
            const running = c.kind === "running";
            const done = c.kind === "done";
            const failed = c.kind === "fail" || c.kind === "done-empty";
            const hoverKey = c.key;
            const clickable = done;
            const tile = (
              <div
                className={"mgdock-tile" + (done ? " done" : "") + (running ? " running" : "") + (failed ? " fail" : "")}
                style={{ width: tw, height: th, cursor: clickable ? "pointer" : "default" }}
                onMouseEnter={() => setHover(hoverKey)}
                onMouseLeave={() => setHover(null)}
                onClick={clickable ? () => onPrefill(j.job_id, c.mid) : undefined}
                title={running
                  ? "Generating " + c.tag + (c.count > 1 ? " · " + c.count + " images" : "")
                  : failed
                  ? (j.error || j.status || "failed")
                  : "Reuse prompt & core settings from " + c.tag + (c.total > 1 ? " · image " + (c.idx + 1) + "/" + c.total : "")}
              >
                {done ? (
                  <img className="mgdock-tileimg" src={"/thumbs/" + encodeURIComponent(c.mid) + ".jpg"} alt="" />
                ) : null}
                {running && c.count > 1 ? (
                  <div className="mgdock-batchgrid">
                    {Array.from({ length: c.count }).map((_, i) => (
                      <i key={i}><span className="mgdock-eclipse sm"><span /></span></i>
                    ))}
                  </div>
                ) : running ? (
                  <span className="mgdock-eclipse lg"><span /></span>
                ) : null}
                {failed && <span className="mgdock-tilefail">⚠</span>}
                {done && (
                  <div className={"mgdock-tilehint" + (hover === hoverKey ? " show" : "")}>
                    <span>Reuse prompt &amp; settings →</span>
                  </div>
                )}
              </div>
            );
            // Cost is TASK-level (one job, possibly N images) -- shown once per
            // job, on its first tile, rather than repeated per tile where it
            // would read as if each image cost that much on its own.
            const showCost = c.idx === undefined || c.idx === 0;
            return (
              <div className="mgdock-run" key={c.key} style={{ width: tw }}>
                {tile}
                <div className="mgdock-runcap">
                  <span className="mgdock-runtag">{c.tag}{c.total > 1 ? "·" + (c.idx + 1) : ""}</span>
                  {showCost && typeof j.paid_credit === "number" && isFinite(j.paid_credit) ? (
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

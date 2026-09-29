import React, { useEffect, useState } from "react";
import { apiGet } from "../api.js";
import { costColor, costText } from "../gen/historyCore.js";
import { WAIT_MIN_TILE, queueWaitText } from "../gen/queueWait.js";
import { matrixGrid } from "../gen/templateCore.js";
import { RunningFace, ClusterFace, tipEnter } from "./HistoryStrip.jsx";
import "../styles/runs.css";

/* Session M (NOTES 8, page M6): a MATRIX run's cells are grouped into one grid -- the last
   axis across, the rest down, labelled from the run's own axes -- and each cell is a normal
   run (a done cell's click reuses it, its { } inspects it). A cell that was refused, not
   sent or may have started is a peach tile (DECISIONS: refusals are peach, never ruby). The
   run's axes and cell states come from GET /api/generate/runs/<id>, read once per run and
   kept for the page's life (a finished run does not change). */
const runCache = new Map();

function useRunRecord(runId, refreshKey) {
  const [rec, setRec] = useState(() => runCache.get(runId) || null);
  useEffect(() => {
    let live = true;
    const cached = runCache.get(runId);
    if (cached && ["sent", "stopped", "refused"].includes(cached.status)) { setRec(cached); return undefined; }
    apiGet("/api/generate/runs/" + runId).then((d) => {
      if (!live || !d || d.error) return;
      runCache.set(runId, d);
      setRec(d);
    });
    return () => { live = false; };
  }, [runId, refreshKey]);
  return rec;
}

function MatrixBlock({ runId, jobs, th, onPrefill, onInspect }) {
  const rec = useRunRecord(runId, jobs.map((j) => j.status).join(","));
  const axes = rec && rec.axes;
  const byTask = {};
  for (const j of jobs) byTask[j.job_id] = j;
  const cells = rec ? (rec.jobs || []).map((c) => ({ ...c, job: c.task_id ? byTask[c.task_id] : null }))
    : jobs.map((j) => ({ cell: Number(j.cell), task_id: j.job_id, state: "sent", job: j }));
  const grid = matrixGrid(axes, cells);
  if (!grid) return null;
  const rows = grid.rows.length;
  const cellH = Math.max(22, Math.floor((th - 16 - 5 * rows) / Math.max(1, rows)));
  const cellW = Math.max(16, Math.round(cellH * (832 / 1216)));
  return (
    <div className="mgrun-grid" title={"matrix · " + cells.length + " cells"}
      style={{ gridTemplateColumns: "64px repeat(" + grid.across.length + ", " + cellW + "px)" }}>
      <span />
      {grid.across.map((a, i) => <span key={"a" + i} className="mgrun-axis" title={a}>{a}</span>)}
      {grid.rows.map((row, r) => (
        <React.Fragment key={"r" + r}>
          <span className="mgrun-rowlbl" title={row.label}>{row.label}</span>
          {row.cells.map((c, k) => {
            const j = c && c.job;
            const done = j && j.status === "done" && (j.media_ids || []).length;
            const running = j && !["done", "failed", "done_with_errors", "stale"].includes(j.status || "running");
            const held = !c || (!j && c.state !== "sent") || (j && j.status === "failed");
            const why = !c ? "not sent" : c.state === "may_have_started"
              ? "may have started on PixAI — check the Activity tray" : c.state === "refused"
                ? "refused by PixAI" + (c.error ? ": " + c.error : "") : c.state === "not_sent" ? "not sent" : "";
            return (
              <div key={"c" + r + ":" + k}
                className={"mgrun-cell" + (done ? " done" : "") + (held ? " held" : "")}
                style={{ width: cellW, height: cellH }}
                title={(c && c.prompt) ? c.prompt + (why ? " — " + why : "") : why}
                onClick={done ? () => onPrefill(j.job_id, j.media_ids[0]) : undefined}>
                {done ? <img src={"/thumbs/" + encodeURIComponent(j.media_ids[0]) + ".jpg"} alt="" /> : null}
                {running && !done ? <span className="mgrun-axis">…</span> : null}
                {held && !done ? "⚠" : null}
                {c && c.task_id && onInspect ? (
                  <button type="button" className="mgrun-cellinsp" title="Inspect the request"
                    onClick={(e) => { e.stopPropagation(); onInspect(c.task_id); }}>{"{ }"}</button>
                ) : null}
              </div>
            );
          })}
        </React.Fragment>
      ))}
    </div>
  );
}

/* The dock's RUNS REEL (design spec C3a, Frontend Gallery.dc.html ~1845-2060),
   rebuilt against the real click/prefill/batch behavior spec (2026-08-02) --
   bound to REAL /api/jobs data, never the DC's SEEDED demo runs.

   TODAY ONLY (History pass, 2026-08-17): the 7-day, per-day timeline is HistoryStrip.jsx
   (its own dock mode, GET /api/next/history); this reel is the DC's single unlabeled
   'today' bucket. Running tiles carry the same mascot + halo + shimmer as History's
   (RunningFace / ClusterFace, shared), cost strings come from historyCore's ONE
   formatter, and the tooltip on every single tile is hoisted to the dock (`onTip`) --
   no native `title` on a tile.

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

   QUEUE WAIT (2026-09-04, ROADMAP's last slice of "starts in ~N"): the one number
   PixAI DOES publish is the queue wait for the model a task was submitted with.
   It is recorded once, when the job was first seen queued (GET /v2/task/wait-time;
   see moonglade_gallery._note_gen_phase) and rides every /api/jobs row as
   `eta_seconds` -- the same feed and the same fetch this reel already makes, so
   surfacing it costs no second poll of PixAI. The Activity tray has shown it since
   2026-07-25 (notify/ActivityRow.jsx's .at-eta chip); a queued reel tile showed
   nothing at all. It now carries the SAME figure in the SAME words, from the one
   shared rule in gen/queueWait.js.

   WHERE it sits, and why not the caption: the caption's second slot is the cost
   line, and it is one line wide on a portrait column. Measured against the
   committed CSS (react-dom/server + the real stylesheet, every reel tier): the
   slot leaves 52px beside the #tag at the 132px tier and 34px at 96px, while
   "est. 27s wait" needs 51px and "est. 1m 35s wait" needs 67px -- so the caption
   clips the word the whole readout depends on. It goes INSIDE the tile instead,
   bottom-anchored above the shimmer, which is where this tile already puts text
   (.mgdock-vtag, .mgdock-tilehint) and where the full tile width is available.
   The cost line is untouched.

   It is a QUEUE wait, never a render ETA: nothing ticks, nothing recomputes, and
   queueWaitText() returns "" the moment `started` flips true or the job goes
   terminal -- so the readout disappears when the task leaves the queue.

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

// The job record as a tooltip row (historyCore.tipLines shape): the log carries no
// model / dims / prompt, so those lines simply are not written; the tag is the job's,
// the time its start, the cost its settled paid_credit.
function tipRow(j, c) {
  // the reel's own verdict (a stale job is terminal here, see isRunningJob)
  const state = c.kind === "running" ? "running" : c.kind === "done" ? "done" : "failed";
  return {
    task_id: j.job_id, media_id: c.mid || null, kind: "image", state,
    ts: Number(j.started_at || j.ts || 0), w: null, h: null, prompt: null, model: null,
    paid_credit: typeof j.paid_credit === "number" ? j.paid_credit : null,
  };
}

export default function RunsReel({ jobs, reelH, onPrefill, onTip, onInspect }) {
  const [hover, setHover] = useState(null);

  // the DC's single unlabeled 'today' bucket (groupDefs 2681 `[['', 'today']]`)
  const midnight = new Date();
  midnight.setHours(0, 0, 0, 0);
  const t0 = midnight.getTime() / 1000;
  const today = jobs.filter((j) => Number(j.started_at || j.ts || 0) >= t0);
  const empty = !today.length;

  const th = Math.max(44, reelH || 132);
  // Aspect-true would need per-run w/h; the job log has none, so every tile
  // takes the DC's fallback ratio (832×1216).
  const tw = Math.max(44, Math.round(th * (832 / 1216)));

  const leave = () => { setHover(null); if (onTip) onTip(null); };
  // Unmount cleanup (#27), same as HistoryStrip: the tooltip is hoisted to the dock, so if
  // the reel unmounts mid-hover (a resize flipping reelVisible) it lingered at stale coords.
  useEffect(() => () => { if (onTip) onTip(null); }, [onTip]);

  return (
    <div className="mgdock-reel">
      {empty && (
        <div className="mgdock-reelempty">
          <div className="mgdock-firstrun" style={{ height: th }}>first run</div>
          <div className="mgdock-emptycopy">
            Runs appear here as they resolve, newest first — they never push the
            composer down, and the reel keeps its own history.
          </div>
        </div>
      )}
      {!empty && (
        <div className="mgdock-reelgrp">
          {groupMatrix(today).map((item) => item.matrix ? (
            <MatrixBlock key={"m:" + item.run} runId={item.run} jobs={item.jobs} th={th}
              onPrefill={onPrefill} onInspect={onInspect} />
          ) : cellsFor(item.job).map((c) => {
            const j = c.job;
            const running = c.kind === "running";
            const cluster = running && c.count > 1;
            const done = c.kind === "done";
            const failed = c.kind === "fail" || c.kind === "done-empty";
            const hoverKey = c.key;
            // Video jobs reach this reel too (the dock's video submits register as
            // type:"generate" -- App.jsx / notify/jobs.js). onPrefill IS prefillRun, the
            // kind-routing dispatcher (GenerateDrawer): a finished video tile routes to
            // prefillVideoFromRun -> the Video tab, an image tile to prefillFromRun. So a
            // done video is remixable straight from the reel, exactly as it is from History
            // -- the old wrong-tab misfire (§2.1) is gone now that the click routes by kind,
            // not because video is excluded. The reel IS the live history; a video that
            // can't be reopened there isn't a history.
            const clickable = done;
            // "" unless PixAI has accepted this job, no worker has taken it, and the log
            // carries the estimate it gave at that moment (gen/queueWait.js owns all three
            // conditions). Batches included: a queued cluster waits like anything else.
            // The tier floor is the same "no room, no render" rule the reel applies to
            // itself (dockLayout's REEL_MIN_ROOM) -- see WAIT_MIN_TILE for the measurements.
            const wait = th >= WAIT_MIN_TILE ? queueWaitText(j) : "";
            const enter = cluster ? undefined : tipEnter(onTip, tipRow(j, c));
            const tile = (
              <div
                className={"mgdock-tile" + (done ? " done" : "") + (running ? " running" : "") + (failed ? " fail" : "")}
                style={{ width: tw, height: th, cursor: clickable ? "pointer" : "default" }}
                onMouseEnter={cluster ? undefined : (ev) => { setHover(hoverKey); enter(ev); }}
                onMouseLeave={cluster ? undefined : leave}
                onClick={clickable ? () => { if (onTip) onTip(null); onPrefill(j.job_id, c.mid); } : undefined}
              >
                {done ? (
                  <img className="mgdock-tileimg" src={"/thumbs/" + encodeURIComponent(c.mid) + ".jpg"} alt="" />
                ) : null}
                {cluster ? <ClusterFace count={c.count} /> : running ? <RunningFace /> : null}
                {wait ? (
                  <span className={"mgdock-runwait" + (cluster ? " up" : "")}>{wait}</span>
                ) : null}
                {failed && <span className="mgdock-tilefail">⚠</span>}
                {done && (
                  <div className={"mgdock-tilehint" + (hover === hoverKey ? " show" : "")}>
                    <span>Use these settings →</span>
                  </div>
                )}
                {/* Session M (NOTES 7): { } Inspect the request this task was sent with */}
                {done && onInspect && c.idx === 0 && /^\d+$/.test(String(j.job_id)) ? (
                  <button type="button" className="mgrun-tileinsp" title="Inspect the request"
                    onClick={(e) => { e.stopPropagation(); if (onTip) onTip(null); onInspect(j.job_id); }}>{"{ }"}</button>
                ) : null}
              </div>
            );
            // Cost is TASK-level (one job, possibly N images) -- shown once per
            // job, on its first tile, rather than repeated per tile where it
            // would read as if each image cost that much on its own.
            const showCost = c.idx === undefined || c.idx === 0;
            const state = running ? "running" : done ? "done" : "failed";
            const cost = showCost && !cluster ? costText(typeof j.paid_credit === "number" ? j.paid_credit : null, state) : "";
            return (
              <div className="mgdock-run" key={c.key} style={{ width: tw }}>
                {tile}
                <div className="mgdock-runcap">
                  <span className="mgdock-runtag">{c.tag}{c.total > 1 ? "·" + (c.idx + 1) : ""}</span>
                  {cost ? (
                    <span className="mgdock-runcost" style={{ color: costColor(j.paid_credit, state, "caption") }}>{cost}</span>
                  ) : null}
                </div>
              </div>
            );
          }))}
        </div>
      )}
    </div>
  );
}

/* The reel's items in order: an ordinary job, or ONE matrix block standing where its
   newest cell stands (the jobs arrive newest first). */
function groupMatrix(jobs) {
  const out = [];
  const seen = {};
  for (const j of jobs) {
    if (j.run_mode === "matrix" && j.run) {
      if (seen[j.run]) { seen[j.run].jobs.push(j); continue; }
      const item = { matrix: true, run: j.run, jobs: [j] };
      seen[j.run] = item;
      out.push(item);
    } else {
      out.push({ job: j });
    }
  }
  return out;
}

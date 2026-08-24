import React, { useCallback, useEffect, useRef, useState } from "react";
import { apiGet } from "../api.js";
import {
  HISTORY_DAYS, anyRunning, costColor, costText, dayCells, dayLabel, mergeHistoryPages,
  olderLabel, tipLines, todayKey, tzMinutes,
} from "../gen/historyCore.js";

/* The dock's HISTORY mode -- the runs strip in a different mode (Frontend Gallery.dc.html
   C3a: the same reel element 1121/3534, groups 1122-1196, "Load older" 1197-1199; DECISIONS
   "Generate dock History -- LOCKED", 2026-08-16). One sideways-scrolling strip; per LOCAL
   day: the shipped hairline+small-caps divider carrying the day, "No runs" when empty, and
   a 2-row column-flow grid of fixed-96px aspect-true tiles, newest first, top-then-bottom.
   "Load N older days ⌄" at the trailing end appends pages.

   CONTENT IS REAL: GET /api/next/history (catalog rows by created_at, bucketed by local day
   server-side, jobs.jsonl live rows merged and deduped) replaces the DC's SEEDED stand-ins.
   Thumbs are the real /thumbs/<mid>.jpg (video rows use the same poster). Cost is the
   settled `paid_credit` through historyCore's ONE formatter. There is no per-image progress
   signal, so a running tile is the dim ground + the generation mascot + an indeterminate
   shimmer -- never a percentage.

   The tooltip on every single tile is NOT rendered here: its state is hoisted to
   GenerateDrawer (`onTip`), which mounts <RunTip> as a SIBLING of the transformed .mgdock
   aside (position: fixed inside a transformed ancestor would re-anchor to the dock). */

const MASCOT = "/branding/mascots/gen_nel.png";
const thumbUrl = (mid) => "/thumbs/" + encodeURIComponent(mid) + ".jpg";
const dropImg = (e) => e.currentTarget.remove();

/* The RUNNING face (DC 1162-1169 mascot + halo over the dim ground; Respec 88-90 the
   indeterminate shimmer). Shared with RunsReel: the same DC tile in both modes. */
export function RunningFace() {
  return (
    <>
      <div className="mgdock-runface">
        <div className="mgdock-runmascotwrap">
          <div className="mgdock-runhalo" />
          <img className="mgdock-runmascot" src={MASCOT} alt="" onError={dropImg} />
        </div>
      </div>
      <div className="mgdock-shim"><i /></div>
    </>
  );
}

/* The batch CLUSTER's inside (DC 1136-1154): the 2×2 grid of dim cells + the footer with the
   16px mascot chip and the same shimmer. Shared with RunsReel. */
export function ClusterFace({ count }) {
  return (
    <>
      <div className="mgdock-batchgrid">
        {Array.from({ length: Math.max(1, Math.min(4, count || 1)) }).map((_, i) => <i key={i} />)}
      </div>
      <div className="mgdock-clusterfoot">
        <span className="mgdock-mascotchip" />
        <div className="mgdock-shim"><i /></div>
      </div>
    </>
  );
}

/* The run TOOLTIP (DC 1594-1605, runTipStyle 3530): tag + local time on one baseline row ·
   model · dims (· duration) · one-line prompt · cost. Lines the row has no data for are
   simply not written (no fake dims, no fake prompt). Positioned by the tile's viewport
   rect: X = centre, Y = top; the CSS pops it up by its own height + 8px. */
export function RunTip({ tip }) {
  if (!tip || !tip.lines) return null;
  const L = tip.lines;
  return (
    <div className="mgdock-runtip" style={{ left: tip.x, top: tip.y }} role="tooltip">
      <div className="row">
        <span className="tag">{L.tag}</span>
        <span className="time">{L.time}</span>
      </div>
      <div className="model">{L.model}</div>
      {L.dims ? <div className="dims">{L.dims}</div> : null}
      {L.prompt ? <div className="prompt">{L.prompt}</div> : null}
      {L.cost ? <div className="cost" style={{ color: L.costColor }}>{L.cost}</div> : null}
    </div>
  );
}

// mouseenter -> the tile's rect drives the tooltip (DC 2711-2713: currentTarget = the tile)
export function tipEnter(onTip, row) {
  return (ev) => {
    if (!onTip) return;
    const rect = ev.currentTarget.getBoundingClientRect();
    onTip({ x: Math.round(rect.left + rect.width / 2), y: Math.round(rect.top), lines: tipLines(row) });
  };
}

export default function HistoryStrip({ onPrefill, onTip }) {
  const [page, setPage] = useState(null);      // merged pages (historyCore.mergeHistoryPages)
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(false);
  const [hover, setHover] = useState(null);
  const [popKeys, setPopKeys] = useState(() => new Set());
  const seenRef = useRef(null);                // row keys already on screen (null = never fetched)
  const pageRef = useRef(null);
  pageRef.current = page;
  const aliveRef = useRef(true);
  useEffect(() => () => { aliveRef.current = false; }, []);

  const today = todayKey();
  const tz = tzMinutes();

  const load = useCallback((before) => {
    const url = "/api/next/history?days=" + HISTORY_DAYS + "&tz=" + tz
      + (before ? "&before=" + encodeURIComponent(before) : "");
    setLoading(true);
    return apiGet(url)
      .then((d) => {
        if (!aliveRef.current) return;
        if (!d || d.error || !Array.isArray(d.days)) { setErr(true); return; }
        const merged = mergeHistoryPages(pageRef.current, d);
        // mgPop only for rows that arrived while the strip was open (DC 2696 `age === 'now'`),
        // never on first paint and never for a page of older days
        const keys = [];
        merged.days.forEach((day) => dayCells(day.rows).forEach((c) => keys.push(c.key)));
        if (seenRef.current === null || before) {
          seenRef.current = new Set(keys);
        } else {
          const fresh = new Set();
          keys.forEach((k) => { if (!seenRef.current.has(k)) fresh.add(k); });
          if (fresh.size) setPopKeys((old) => { const n = new Set(old); fresh.forEach((k) => n.add(k)); return n; });
          seenRef.current = new Set(keys);
        }
        setErr(false);
        setPage(merged);
      })
      .catch(() => { if (aliveRef.current) setErr(true); })
      .finally(() => { if (aliveRef.current) setLoading(false); });
  }, [tz]);

  // first page on mount; refresh on the same completion channels the reel listens on
  useEffect(() => {
    load();
    const onEvt = () => load();
    window.addEventListener("mg-gen-done", onEvt);
    document.addEventListener("mg-submit", onEvt);
    document.addEventListener("mg-result", onEvt);
    return () => {
      window.removeEventListener("mg-gen-done", onEvt);
      document.removeEventListener("mg-submit", onEvt);
      document.removeEventListener("mg-result", onEvt);
    };
  }, [load]);
  // an 8s poll only while something is still running
  const running = anyRunning(page);
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => load(), 8000);
    return () => clearInterval(t);
  }, [running, load]);
  // the tooltip must not outlive the strip (prefill closes History under the pointer)
  useEffect(() => () => { if (onTip) onTip(null); }, [onTip]);

  const days = page ? page.days : [];
  const canLoadMore = !!(page && page.has_more && page.next_before && !loading);
  const label = olderLabel(page, loading, today);

  return (
    <div className="mgdock-reel">
      {err && !page && <div className="mgdock-noruns">History unavailable</div>}
      {days.map((day) => {
        const cells = dayCells(day.rows);
        return (
          <div className="mgdock-reelgrp" key={day.date}>
            <div className="mgdock-daydiv">
              <i />
              <span>{dayLabel(day.date, today)}</span>
              <i />
            </div>
            {!cells.length && <div className="mgdock-noruns">No runs</div>}
            <div className="mgdock-histgrid">
              {cells.map((c) => {
                const r = c.row;
                const done = c.kind === "done";
                const running1 = c.kind === "running";
                const cluster = c.kind === "cluster";
                const failed = c.kind === "fail";
                // a DONE tile prefills -- images into the Image tab, videos into the Video tab
                // (the host's onPrefill routes by kind, SCOPE_2026-08-17 §2); running / failed /
                // clusters have no click action
                const clickable = done;
                const single = !cluster;
                const enter = single ? tipEnter(onTip, r) : undefined;
                return (
                  <div className={"mgdock-run" + (popKeys.has(c.key) ? "" : " still")} key={c.key}
                    style={{ width: c.size.w }}>
                    <div
                      className={"mgdock-tile" + (done ? " done" : "") + (running1 || cluster ? " running" : "") + (failed ? " fail" : "")}
                      style={{ width: c.size.w, height: c.size.h, cursor: clickable ? "pointer" : "default" }}
                      onMouseEnter={single ? (ev) => { setHover(c.key); enter(ev); } : undefined}
                      onMouseLeave={single ? () => { setHover(null); if (onTip) onTip(null); } : undefined}
                      onClick={clickable ? () => { if (onTip) onTip(null); onPrefill(r.task_id || "", r.media_id); } : undefined}
                    >
                      {done && <img className="mgdock-tileimg" src={r.thumb || thumbUrl(r.media_id)} alt="" />}
                      {c.video && <span className="mgdock-vtag">▶ video</span>}
                      {running1 && <RunningFace />}
                      {cluster && <ClusterFace count={c.count} />}
                      {failed && <span className="mgdock-tilefail">⚠</span>}
                      {clickable && (
                        <div className={"mgdock-tilehint" + (hover === c.key ? " show" : "")}>
                          <span>Use these settings →</span>
                        </div>
                      )}
                    </div>
                    <div className="mgdock-runcap">
                      <span className="mgdock-runtag">{cluster ? c.count + " images cooking" : c.tag}</span>
                      {failed ? (
                        <span className="mgdock-runcost">{r.state === "stale" ? "stalled" : "failed"}</span>
                      ) : !cluster && c.showCost && costText(r.paid_credit, r.state) ? (
                        <span className="mgdock-runcost" style={{ color: costColor(r.paid_credit, r.state, "caption") }}>
                          {costText(r.paid_credit, r.state)}
                        </span>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
      {(page || loading) && (
        <button type="button" className="mgdock-older" disabled={!canLoadMore}
          onClick={canLoadMore ? () => load(page.next_before) : undefined}>
          {label}
        </button>
      )}
    </div>
  );
}

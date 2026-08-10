import { useCallback, useEffect, useRef, useState } from "react";
import { subscribe, openTray, closeTray, dismiss, clearFinished } from "./jobsStore.js";

// Every drawer/sheet/dock in this app animates closed rather than snapping shut (locked
// app-wide rule -- see docs/DECISIONS.md drift item 13). 260ms matches the Loom's own
// side-panel choreography this control is modeled on (jtSlideOut in the DC reference).
const CLOSE_MS = 260;

// Which side of the header the whole control (trigger + panel) docks to -- persisted so
// the choice survives a reload, and shared across hosts (one browser, one localStorage,
// same preference whether you're looking at the gallery or the Loom). A real ask
// (2026-08-09), traced to Job Tracker Fullscreen.dc.html's own ◧Left/Right◨ edge
// selector -- an unshipped exploration doc, not the header-docked pattern that actually
// got built, so this is new work against the real component, not a restore.
const EDGE_KEY = "mg_activity_edge";

function readEdge() {
  try {
    const v = window.localStorage.getItem(EDGE_KEY);
    return v === "left" ? "left" : "right";
  } catch { return "right"; }
}

/* useActivity -- the header-docked Activity control's shared state, one copy consumed by
   each host's own trigger+panel markup (Claude Design handoff 2026-08-09, drift item 39
   replaces the single shared floating <ActivityTray> with per-host chrome, but every host
   still reads the SAME jobsStore -- real /api/jobs truth, every job type, no new endpoint). */
export default function useActivity() {
  const [state, setState] = useState({ jobs: [], open: false });
  const [expandedId, setExpandedId] = useState(null);
  const [closing, setClosing] = useState(false);
  const [edge, setEdgeState] = useState(readEdge);
  const closeTimer = useRef(null);
  useEffect(() => subscribe(setState), []);
  useEffect(() => () => clearTimeout(closeTimer.current), []);

  const setEdge = useCallback((next) => {
    const v = next === "left" ? "left" : "right";
    setEdgeState(v);
    try { window.localStorage.setItem(EDGE_KEY, v); } catch { /* best-effort */ }
  }, []);

  const { jobs, open } = state;

  // The row a popover/expansion was showing is gone (dismissed/aged out) -> close it.
  useEffect(() => {
    if (expandedId && !jobs.find((j) => j.job_id === expandedId)) setExpandedId(null);
  }, [expandedId, jobs]);

  const close = useCallback(() => {
    clearTimeout(closeTimer.current);
    setClosing(true);
    closeTimer.current = setTimeout(() => { closeTray(); setClosing(false); setExpandedId(null); }, CLOSE_MS);
  }, []);
  const toggle = useCallback(() => {
    if (open && !closing) close();
    else { clearTimeout(closeTimer.current); setClosing(false); openTray(); }
  }, [open, closing, close]);
  const toggleRow = useCallback((jid) => {
    setExpandedId((cur) => (cur === jid ? null : jid));
  }, []);

  return {
    jobs, open: open || closing, closing, expandedId, toggle, close, toggleRow, dismiss, clearFinished,
    edge, setEdge,
  };
}

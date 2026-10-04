import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "../api.js";
import { peek, put } from "./swrCache.js";
import { undoSecondsLeft, UNDO_MS } from "../curation/curationCore.js";
import * as fixRun from "../lib/brokenFixRun.js";

/* useBrokenFiles -- Health's Broken files list, one hook for both shells (Session W). The desktop
   section (components/BrokenFiles.jsx, inside HealthOverlay) and the phone screen
   (components/BrokenFilesMobile.jsx, from HealthMobile) consume it, the way useHealth.js serves
   both Health screens.

   doc     GET /api/integrity/broken, painted from the read cache on a reopen and refreshed behind
           it (the same stale-while-revalidate as every Health read).
   run     the fix run (lib/brokenFixRun.js): {status, fixedAt}. The list reloads when it ends.
   mark    Mark lost / Keep as is: a local flag on the server (integrity_marks.json), then the
           Session N toast with a 10 s Undo, which puts back the mark the row had before.
   fix     start a run over [{media_id, action}] (a row's own Re-download / Rebuild, or Fix all),
           each with the action the list showed -- the server runs nothing for a row whose fix
           changed since the check.

   Nothing here deletes anything, and nothing reaches PixAI except the run's re-downloads, which
   the server's own runner gates. */

export const BROKEN_PATH = "/api/integrity/broken";

function csrf() {
  try { return (window.MG_BOOT && window.MG_BOOT.csrf) || ""; } catch { return ""; }
}

export default function useBrokenFiles() {
  const [doc, setDoc] = useState(() => peek(BROKEN_PATH));
  const [err, setErr] = useState(null);
  const [run, setRun] = useState(() => fixRun.snapshot());
  const [now, setNow] = useState(() => Date.now());
  const [toast, setToast] = useState(null);          // {text, tone, prev, until, secs}
  const timer = useRef(0);

  const reload = useCallback(() => apiGet(BROKEN_PATH).then((d) => {
    if (!d || d.error) {
      if (peek(BROKEN_PATH) == null) setErr((d && d.error) || "couldn't load the list");
      return;
    }
    put(BROKEN_PATH, d);
    setDoc(d);
    setErr(null);
    fixRun.resume(d.run);
  }), []);

  useEffect(() => { reload(); }, [reload]);
  useEffect(() => fixRun.subscribe(setRun), []);
  useEffect(() => fixRun.onRunEnd(() => { reload(); }), [reload]);

  // ✓ FIXED lasts 2 s, then the row leaves: tick while any finished row is still inside its 2 s.
  const fixedAt = run.fixedAt || {};
  const young = Object.values(fixedAt).some((t) => now - t < fixRun.FIXED_MS);
  useEffect(() => {
    if (!young) return undefined;
    const t = setTimeout(() => setNow(Date.now()), 250);
    return () => clearTimeout(t);
  }, [young, now]);
  useEffect(() => { setNow(Date.now()); }, [fixedAt]);
  const fixedNow = {};
  const gone = {};
  for (const [mid, t] of Object.entries(fixedAt)) {
    if (now - t < fixRun.FIXED_MS) fixedNow[mid] = true;
    else gone[mid] = true;
  }

  // The Session N toast: one at a time, Undo for 10 s (curation/curationCore.js's own timing).
  const stop = () => { clearInterval(timer.current); timer.current = 0; };
  useEffect(() => stop, []);
  const show = useCallback((text, prev, tone) => {
    stop();
    const until = Date.now() + UNDO_MS;
    setToast({ text, tone: tone || "", prev: prev || null, until, secs: undoSecondsLeft(until, Date.now()) });
    timer.current = setInterval(() => {
      setToast((t) => {
        if (!t) { stop(); return t; }
        const secs = undoSecondsLeft(t.until, Date.now());
        if (secs <= 0) { stop(); return null; }
        return secs === t.secs ? t : { ...t, secs };
      });
    }, 250);
  }, []);
  const dismiss = useCallback(() => { stop(); setToast(null); }, []);

  const mark = useCallback(async (mid, value, text) => {
    const d = await apiPost("/api/integrity/mark", { csrf: csrf(), media_id: mid, mark: value });
    if (!d || d.error) { show((d && d.error) || "Couldn't save that.", null, "peach"); return d; }
    reload();
    show(text, { media_id: mid, mark: d.prev || "" });
    return d;
  }, [reload, show]);

  const undo = useCallback(async () => {
    const t = toast;
    if (!t || !t.prev) return;
    dismiss();
    const d = await apiPost("/api/integrity/mark", { csrf: csrf(), media_id: t.prev.media_id, mark: t.prev.mark });
    if (!d || d.error) { show((d && d.error) || "Couldn't undo that.", null, "peach"); return; }
    reload();
  }, [toast, dismiss, reload, show]);

  const fix = useCallback(async (items) => {
    const d = await fixRun.startFix(items);
    if (d && d.error) show(d.error, null, "peach");
    return d;
  }, [show]);

  const results = {};
  for (const r of ((run.status && run.status.results) || [])) results[r.media_id] = r;

  return {
    doc, err, reload, toast, dismiss, undo, mark, fix, stop: fixRun.stopFix, say: show,
    status: run.status, running: !!(run.status && run.status.running),
    current: run.status && run.status.current, results, fixedNow, gone,
    done: { ...gone, ...fixedNow },   // every row this run already fixed: Fix all never counts it again
    readOnly: !!(doc && doc.read_only),
  };
}

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "../api.js";
import { accountCsrf } from "../hooks/useAccountPrefs.js";
import { submitRun } from "./submitTask.js";
import {
  LOST_WORDS, ackOf, chargeMismatch, readBack, runLine,
} from "./templateCore.js";

/* The Generate dock's run road (Session M, BUILD-w5-m s2-s4): every send of more than one
   generation, and one generation whose prompt uses the template syntax.

   - openConfirm(body)   POST /api/generate/plan (read-only: it writes nothing) and open THE
                         ONE confirm with the server's own count, total and free cards. Cancel
                         sends nothing. There is no "don't ask again" anywhere.
   - go()                the confirm's Go: the synchronous latch, then submitRun ONCE with the
                         confirm's run_id and acknowledgement. The confirm closes on Go.
   - sendSingle(body)    a count-1 send through /run (no confirm, no acknowledgement: it is a
                         single send and the card auto-applies, review F11).

   While the POST is out the run is read back from GET /api/generate/runs/<id> every 2 s: a
   404 means "not received yet", each new task id goes to Jobs.track (its `seen` map
   de-dupes), and a lost POST is never posted again -- it is read back until the run ends or
   the read-back gives up with "may not have reached the server" (review F4, templateCore's
   readBack). Send stays disabled (`busy`) until then. */

export function newRunId() {
  const c = (typeof crypto !== "undefined" && crypto) || null;
  const bytes = new Uint8Array(16);
  if (c && c.getRandomValues) c.getRandomValues(bytes);
  else for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;         // uuid4
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

const POLL_MS = 2000;

export default function useRuns({ openLine, onSettled }) {
  const [confirm, setConfirm] = useState(null);   // {loading?, plan?, error?, body, runId}
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState(null);          // the last run's answer, for Inspect
  const busyRef = useRef(false);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  // A confirm answers the body it was opened for: a newer open or a Cancel retires an older
  // /plan still in flight, so a late answer can never reopen a confirm for stale settings.
  const seq = useRef(0);
  const openConfirm = useCallback(async (body) => {
    const my = ++seq.current;
    setConfirm({ loading: true, body });
    const d = await apiPost("/api/generate/plan", { ...body, csrf: accountCsrf() });
    if (!alive.current || my !== seq.current) return;
    if (d.error) setConfirm({ error: d.error, recipe_error: d.recipe_error || null, body });
    else setConfirm({ plan: d, body, runId: newRunId() });
  }, []);

  const cancel = useCallback(() => { seq.current += 1; setConfirm(null); }, []);

  /* One run, once: the POST through the road, the read-back beside it. */
  const runOnce = useCallback(async (body, runId, ack) => {
    const emit = openLine("Sending…");
    const tracked = {};
    const expectedOf = {};
    const track = (run) => {
      if (!run || !Array.isArray(run.jobs) || !window.Jobs) return;
      for (const j of run.jobs) {
        if (j.expected != null) expectedOf[j.task_id] = j.expected;
        if (!j.task_id || tracked[j.task_id]) continue;
        tracked[j.task_id] = true;
        const cellNo = Number(j.cell) + 1;
        const label = run.jobs.length > 1 ? "Run " + cellNo + "/" + run.jobs.length : "Generated";
        window.Jobs.track(j.task_id, label, (phase, st) => {
          if (phase !== "done") return;
          const data = st || {};
          const exp = data.expected_credit != null ? data.expected_credit : expectedOf[j.task_id];
          const warn = chargeMismatch(cellNo, exp, data.paid_credit);
          if (warn) emit({ kind: "warn", text: warn });
          window.dispatchEvent(new CustomEvent("mg-gen-done"));
          if (window.Ach) window.Ach.check();
        }, j.batch || 1);
      }
    };
    let state = readBack(null, { type: "start", at: Date.now() });
    let timer = 0;
    let stopped = false;
    const paint = (s) => {
      if (s.phase === "lost") { emit({ kind: "warn", text: LOST_WORDS }); return; }
      if (s.run) {
        track(s.run);
        const line = runLine(s.run);
        if (s.phase === "done") emit({ kind: line.kind === "ok" ? "ok" : "warn", text: line.text });
        else emit({ kind: "run", text: "Sending… " + (s.run.jobs || []).filter((j) => j.state === "sent").length + " of " + ((s.run.jobs || []).length || "?") + " sent" });
      }
    };
    const poll = async () => {
      if (stopped) return;
      const d = await apiGet("/api/generate/runs/" + runId);
      if (stopped) return;
      const next = d && d.http_status === 404 ? readBack(state, { type: "get404", at: Date.now() })
        : d && !d.error ? readBack(state, { type: "get", run: d, at: Date.now() }) : state;
      state = next;
      paint(state);
      if (state.phase === "done" || state.phase === "lost") stopped = true;
      else timer = setTimeout(poll, POLL_MS);
    };
    timer = setTimeout(poll, POLL_MS);
    const ans = await submitRun({ ...body, csrf: accountCsrf(), run_id: runId, ...(ack ? { ack } : {}) });
    let result = null;
    if (ans.lost) {
      state = readBack(state, { type: "postLost", at: Date.now() });
      emit({ kind: "run", text: "No answer from the server — reading the run back…" });
      // Keep reading back until the run ends or the window passes. NEVER a second POST.
      await new Promise((resolve) => {
        const wait = () => {
          if (stopped || state.phase === "done" || state.phase === "lost") { resolve(); return; }
          setTimeout(wait, 500);
        };
        wait();
      });
      result = state.run || null;
    } else {
      stopped = true;
      clearTimeout(timer);
      const d = ans.data || {};
      if (d.error && !(Array.isArray(d.jobs) && d.jobs.length)) {
        emit({ kind: "warn", text: d.error });
        result = d;
      } else {
        state = readBack(state, { type: "post", run: d, at: Date.now() });
        paint(state);
        result = d;
      }
    }
    stopped = true;
    clearTimeout(timer);
    if (alive.current) setLast(result);
    return result;
  }, [openLine]);

  const finish = useCallback((res, body) => {
    busyRef.current = false;
    if (alive.current) setBusy(false);
    // A moved price (or any change since the confirm) reopens it with the server's new
    // numbers, a new run id, the same body. Nothing is re-sent on its own.
    if (res && res.plan && alive.current) setConfirm({ plan: res.plan, body, runId: newRunId(), moved: res.error });
    if (onSettled) onSettled(res);
  }, [onSettled]);

  const go = useCallback(async () => {
    if (busyRef.current) return;                 // latch, independent of render timing
    const c = confirm;
    if (!c || !c.plan || c.plan.read_only || !c.runId) return;
    busyRef.current = true;
    setBusy(true);
    setConfirm(null);
    const res = await runOnce(c.body, c.runId, ackOf(c.plan));
    finish(res, c.body);
  }, [confirm, runOnce, finish]);

  const sendSingle = useCallback(async (body) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    const res = await runOnce(body, newRunId(), null);
    finish(res, body);
  }, [runOnce, finish]);

  return { confirm, busy, last, openConfirm, cancel, go, sendSingle, busyRef };
}

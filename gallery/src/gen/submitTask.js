import { useCallback, useRef, useState } from "react";
import { friendlyGenErr } from "./genCore.js";

/* ONE submit path for every spend route the pilot touches (/api/generate,
   /api/edit, /api/fix). The classic has runTask; this is its port, and it exists
   as one function so the spend-safety contract cannot drift between the three
   surfaces the way friendlyGenErr drifted into four hand-maintained copies.

   The contract, enforced here:
   - NO retry, ever. gql_mutate's no-retry covers the server->PixAI hop only; a
     client re-POST creates a second charged task.
   - Errors arrive HTTP 200 {"error": ...}. Key off the body, never r.ok.
   - `adjusted` lands on the persistent result line, not only a toast.
   - A transport failure after submit says the task MAY exist -- never invites a
     resubmit.
   - Completion rides Jobs.track, whose callback is cb(phaseString, data).
   - `payload.count` (image gen only; absent on edit/fix) rides along to Jobs.track
     so the Runs reel can render a real "N requested" placeholder while a multi-image
     task is still running instead of one generic tile (2026-08-02, verify-flagged
     gap in the reel rebuild -- see RunsReel.jsx).

   `emit(patch)` is how the caller paints its own result line; it is called with
   {text, kind, media?} patches. Returns the task_id, or null. */
export async function submitTask(route, payload, { label, emit }) {
  let d;
  try {
    const r = await fetch(route, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    d = await r.json();
  } catch {
    emit({
      kind: "err",
      text: "No answer from the server — the task MAY still have been submitted. Check the Activity tray before trying again.",
    });
    return null;
  }
  if (d.error || !d.task_id) {
    emit({ kind: "err", text: friendlyGenErr(d.error || "Submit failed.") });
    return null;
  }
  const adj = (d.adjusted || [])
    .map((a) => a.field + " " + a.asked + "→" + a.used).join(", ");
  if (adj && window.Toast) {
    window.Toast.show({
      kind: "err", title: "Settings were adjusted before submitting", msg: adj,
    });
  }
  emit({ text: "Queued — running…" + (adj ? "  (adjusted: " + adj + ")" : "") });

  if (!window.Jobs) {
    emit({
      kind: "ok",
      text: "Submitted — task " + d.task_id +
            ". Live tracking is unavailable on this page; it will land in your library.",
    });
    return d.task_id;
  }
  window.Jobs.track(d.task_id, label, (phase, st) => {
    const data = st || {};
    if (phase === "done") {
      const paid = data.paid_credit;
      emit({
        kind: "ok",
        text: paid === 0 ? "free (card used)"
            : paid == null ? "done"
            : Number(paid).toLocaleString() + " credits",
        media: data.media_ids || [],
      });
      window.dispatchEvent(new CustomEvent("mg-gen-done"));
      // Nudge the Folio of Honors to check-and-celebrate any newly earned achievement.
      // Generations complete through this path independent of ActionsMenu's mutations,
      // so it needs its own call here rather than relying solely on App.jsx's
      // mg-gen-done listener.
      if (window.Ach) window.Ach.check();
    } else if (phase === "failed") {
      emit({
        kind: "err",
        text: friendlyGenErr(data.error || data.reason || data.status || "failed"),
      });
    } else if (phase === "stalled") {
      emit({
        kind: "err",
        text: "This tab stopped watching after 6h — the task may still finish; check the Activity tray.",
      });
    }
  }, payload.count);
  return d.task_id;
}

/* The result-line list every tab keeps: one line per submission, so concurrent
   submits each own their own status (the classic's per-submission
   .gen-result-line). `open(text)` appends a line and returns the emit function
   bound to it -- the id lives in a ref so it survives every re-render. */
export function useResultLines() {
  const [lines, setLines] = useState([]);
  const seq = useRef(0);
  const open = useCallback((text) => {
    const id = "line-" + (++seq.current);
    setLines((old) => old.concat([{ id, text, kind: "run" }]));
    return (patch) =>
      setLines((old) => old.map((x) => (x.id === id ? { ...x, ...patch } : x)));
  }, []);
  return [lines, open];
}

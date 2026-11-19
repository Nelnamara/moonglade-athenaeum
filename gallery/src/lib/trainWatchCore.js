/* lib/trainWatchCore.js -- the pure half of "LoRA training says when it finishes"
   (2026-11-18). notify/trainWatch.js does the reading; this decides.

   The source is the one the Train screens already poll: /api/train/runs (`?running=1` is the
   light read of what is queued or training). A run seen running and then gone from that list
   has ended; the full list says how (done or failed), and the corner notice says it once. */

const LIVE = new Set(["running", "waiting"]);

/* id -> title of every run the read says is queued or training. */
export function liveRuns(d) {
  const out = new Map();
  if (!d || typeof d !== "object") return out;
  for (const r of [...(d.running || []), ...(d.runs || [])]) {
    if (r && r.id && LIVE.has(r.status)) out.set(String(r.id), String(r.title || ""));
  }
  return out;
}

/* The watched ids that are no longer live. */
export function ended(watched, live) {
  return [...(watched || new Map()).keys()].filter((id) => !live.has(id));
}

/* The corner notice for a run that ended, or null when its row says it has not (or is not
   there: then nothing is said rather than a guess). */
export function finishNotice(row, title) {
  if (!row || typeof row !== "object") return null;
  const name = String(row.title || title || "Your LoRA");
  if (row.status === "done") {
    return { kind: "ok", title: "Training finished", msg: name + " is ready — Train › Runs has it." };
  }
  if (row.status === "failed") {
    return { kind: "err", sticky: true, title: name + " — training failed",
             msg: row.reason ? String(row.reason) : "Train › Runs says what happened." };
  }
  return null;
}

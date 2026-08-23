/* notify/jobs.js -- the SPEND-CRITICAL Jobs engine, ported verbatim from static/mg-notify.js's
   Jobs IIFE (no-vanilla campaign, component 6). A MODULE SINGLETON, deliberately outside any
   React lifecycle: Jobs.track's poll loop is what drives a PAID generation's completion callback
   (the download + catalog insert), and it must keep ticking to a terminal phase after the
   launching UI (the Generate dock, a mobile screen) closes or unmounts. Each poll chain is a
   self-perpetuating setTimeout closure holding no component reference -- exactly the property
   that made the vanilla survive the drawer closing, preserved here on purpose.

   SPEND-SAFETY CONTRACT (do not weaken):
   - This module NEVER submits or spends. It GETs /api/task-status and POSTs job METADATA to
     /api/jobs (fire-and-forget). The only retries are idempotent READS (again(4000) on a fetch
     reject) -- a transient network blip keeps watching, it never re-submits anything.
   - `seen` de-dupes BOTH entry points: a stray double-call for one task_id can neither
     double-POST /api/jobs nor start two poll loops. It is a true module singleton.
   - register() is register-ONLY (no poll) for hosts that own a hardened poll loop already (the
     Loom's pollShot/pollImg); track() owns registration + polling for hosts without one (the
     gallery's submitTask). Keeping the split avoids a redundant second poller whose duplicate
     completion side effects could double-download.
   - The 6h wall-clock ceiling ('stalled', t0 threaded through the recursion) stops a stuck task
     from pinning the tab against the server forever. 'stalled' is deliberately NOT 'failed':
     elapsed time is not evidence the task died, only that this tab stopped watching -- a reload
     resumes.
   - The cadence STEPS DOWN as a task ages (notify/pollCadence.js): 3s, then 20s past 20min,
     then 3min past 90min, then the ceiling. Video renders are the reason -- a clip can run for
     an hour, and asking every 3s for an hour is an hour of pointless traffic. Image/edit/fix
     ride the same table and never reach the first step, which is the point: one table, no
     per-route copies. */

import { refresh as trayRefresh } from "./jobsStore.js";
import { cadenceFor } from "./pollCadence.js";

const seen = {};

export function register(id, label, count) {
  if (!id || seen[id]) return;
  seen[id] = true;
  // count: how many images this ONE task renders (1-4, image-gen only). Omitted by callers
  // that don't know it -- JSON.stringify drops an undefined key, so those registrations are
  // byte-identical to before the param existed.
  fetch("/api/jobs", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_id: id, type: "generate", label: label || "Generation", status: "running", count }),
  }).catch(() => {});
  trayRefresh();
}

export function track(id, label, cb, count) {
  if (!id || seen[id]) return;
  register(id, label, count);
  poll(id, cb);
}

/* The callback contract, as hosts see it:
   - "running"  -- every non-terminal poll, with the /api/task-status body.
   - "slow" / "stale" -- ONCE, on ENTERING that tier, in addition to that poll's "running".
     Once, not every poll, because these are a host's cue to change its wording, and a host
     that wants a live elapsed readout already has one on every "running" tick. The tier is
     threaded through the recursion beside t0, so re-entering is impossible and a tab that was
     backgrounded across two thresholds simply reports the tier it woke up in.
   - "done" / "failed" -- terminal, from the server.
   - "stalled" -- the 6h ceiling: this tab stopped asking. Not a verdict on the task. */
function poll(id, cb, startedAt, tier) {
  const t0 = startedAt || Date.now();
  const from = tier || "normal";
  /* One scheduling decision, taken off the shared tier table. `floorMs` is the network-blip
     retry floor: a rejected fetch has always backed off further than the normal cadence
     (again(4000)), and that stays true at every tier -- an idempotent READ retry, never a
     resubmit. */
  function again(d, floorMs) {
    const c = cadenceFor(Date.now() - t0);
    if (c.tier === "stalled") {
      if (cb) cb("stalled", {
        phase: "stalled",
        error: "Stopped checking after 6h — the task may still be running. "
          + "Reload to resume watching, or check it on pixai.art.",
      });
      trayRefresh();
      return;
    }
    if (cb && c.tier !== from && (c.tier === "slow" || c.tier === "stale")) cb(c.tier, d || {});
    setTimeout(() => poll(id, cb, t0, c.tier), floorMs ? Math.max(c.ms, floorMs) : c.ms);
  }
  fetch("/api/task-status?task_id=" + encodeURIComponent(id))
    .then((r) => r.json())
    .then((d) => {
      if (d.phase === "done") { if (cb) cb("done", d); trayRefresh(); }
      else if (d.phase === "failed") { if (cb) cb("failed", d); trayRefresh(); }
      else { if (cb) cb("running", d); again(d, 0); }
    })
    .catch(() => again(null, 4000));
}

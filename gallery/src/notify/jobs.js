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
     resumes. */

import { refresh as trayRefresh } from "./jobsStore.js";

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

const POLL_CEILING_MS = 6 * 60 * 60 * 1000;

function poll(id, cb, startedAt) {
  const t0 = startedAt || Date.now();
  function again(ms) {
    if (Date.now() - t0 > POLL_CEILING_MS) {
      if (cb) cb("stalled", {
        phase: "stalled",
        error: "Stopped checking after 6h — the task may still be running. "
          + "Reload to resume watching, or check it on pixai.art.",
      });
      trayRefresh();
      return;
    }
    setTimeout(() => poll(id, cb, t0), ms);
  }
  fetch("/api/task-status?task_id=" + encodeURIComponent(id))
    .then((r) => r.json())
    .then((d) => {
      if (d.phase === "done") { if (cb) cb("done", d); trayRefresh(); }
      else if (d.phase === "failed") { if (cb) cb("failed", d); trayRefresh(); }
      else { if (cb) cb("running", d); again(3000); }
    })
    .catch(() => again(4000));
}

/* notify/jobsStore.js -- the Activity-tray state machine, ported from static/mg-notify.js's
   JobsCard IIFE (no-vanilla campaign, component 6) with the DOM rendering removed to React
   (<ActivityTray>). A MODULE SINGLETON: the adaptive poll loop, the transition-toast memory
   (`last`/`seeded`) and the open/closed persistence all live here, independent of any view --
   recreating them per-mount is the double-toast-the-whole-backlog bug the vanilla's module
   scoping existed to prevent.

   Renders SERVER TRUTH: /api/jobs is the log (survives reload); this store GETs it, fires
   transition toasts, and hands the rows to React. It never talks to /api/task-status and never
   drives a spend callback -- that is notify/jobs.js's job. They meet only at refresh().

   Poll cadence (verbatim): 2500ms while anything is running, else 7000ms; document.hidden
   reschedules WITHOUT fetching (pauses in a background tab). Busy is derived from the fetched
   rows (running > 0) rather than read back off a DOM class like the vanilla did -- same value,
   no DOM dependency. */

import { apiGet, apiPost } from "../api.js";
import { show as toastShow } from "./toastStore.js";

const LSK = "mg_jobs_open";

let jobs = [];
let open = false;
let started = false;
let timer = null;
let seeded = false;
const last = {};            // job_id -> previous status, for transition toasts
const subs = new Set();

function emit() { subs.forEach((fn) => fn({ jobs, open })); }

export function subscribe(fn) {
  subs.add(fn);
  fn({ jobs, open });
  return () => subs.delete(fn);
}

export function getState() { return { jobs, open }; }
export function runningCount() {
  return jobs.filter((j) => (j.status || "running") === "running").length;
}

function readOpen() {
  try { return localStorage.getItem(LSK) === "1"; } catch { return false; }
}
function setOpen(v) {
  try { localStorage.setItem(LSK, v ? "1" : "0"); } catch { /* private mode */ }
  open = !!v;
  emit();
}
export function openTray() { setOpen(true); refresh(); }
export function closeTray() { setOpen(false); }

/* `stale` toasts alongside the real terminal statuses even though the server keeps it OUT of
   its own terminal set on purpose (resolve_orphan_jobs -- a later sweep can still resolve the
   job for real). It is written for a generation PixAI accepted and never dispatched, or one
   stuck so long the server can no longer reach PixAI to ask. Leaving it out here meant the one
   outcome nobody can see coming was also the only one that arrived in silence: five unstarted
   generations died unnoticed that way. Keep stale in this map. */
const TERMINAL = { done: 1, failed: 1, done_with_errors: 1, stale: 1 };

function toastTransitions(rows) {
  rows.forEach((j) => {
    const st = j.status || "running";
    const prev = last[j.job_id];
    // A claim row is BORN terminal (the server writes it "done" -- claiming is
    // instantaneous), so the transition rule below would read its first appearance as a
    // just-finished job and toast "— done / Added to your gallery." Wrong on both counts:
    // nothing was added to the gallery, and the claim already toasted its real "+N
    // credits" at the moment of the click, seconds before this poll. The tracker LINE is
    // what this feature adds; the toast was never missing.
    if (j.type === "claim") { last[j.job_id] = st; return; }
    // THE OLD UPDATE SUCCESS TOAST, retired 2026-09-04 (Identity Chrome handoff C2: "the
    // modal IS the receipt"). An update row is born terminal the same way a claim row is
    // -- the server writes "Updated Moonglade / done" and only THEN restarts -- so the
    // rule below read its first appearance as a just-finished job and fired
    // "Updated Moonglade — done / Added to your gallery." Wrong twice over: nothing was
    // added to the gallery, and the update modal was at that moment sitting right there
    // showing its own three-phase account of the same event. The tracker LINE stays (the
    // activity log is the only record of an update that failed while nobody was watching);
    // the toast was the duplicate.
    if (j.type === "update") { last[j.job_id] = st; return; }
    if (seeded && !TERMINAL[prev] && TERMINAL[st]) {
      if (st === "done") {
        const mid = (j.media_ids || [])[0] || "";
        toastShow({
          kind: "ok", title: (j.label || "Generation") + " — done", msg: "Added to your gallery.",
          thumb: mid ? "/thumbs/" + encodeURIComponent(mid) + ".jpg" : null,
        });
      } else if (st === "done_with_errors") {
        toastShow({
          kind: "err", sticky: true, title: (j.label || "Job") + " finished with errors",
          msg: j.error || "Some files failed — see the activity card.",
        });
      } else if (st === "stale") {
        // Deliberately not worded as a failure -- nothing reported one. The server writes the
        // message that says WHICH stall it is (never dispatched vs unreachable); pass it through.
        toastShow({
          kind: "err", sticky: true, title: (j.label || "Job") + " — stalled",
          msg: j.error || "See the activity card.",
        });
      } else {
        toastShow({
          kind: "err", sticky: true, title: (j.label || "Job") + " failed",
          msg: j.error || "See the activity card.",
        });
      }
    }
    last[j.job_id] = st;
  });
  seeded = true;
}

export function refresh() {
  return apiGet("/api/jobs")
    .then((d) => {
      const rows = (d && d.jobs) || [];
      toastTransitions(rows);
      jobs = rows;
      emit();
    })
    .catch(() => {});
}

function schedule() {
  if (timer) clearTimeout(timer);
  const busy = runningCount() > 0;
  timer = setTimeout(() => {
    if (document.hidden) { schedule(); return; }
    refresh().then(schedule);
  }, busy ? 2500 : 7000);
}

export function dismiss(id) {
  apiPost("/api/jobs/dismiss", { job_id: id })
    .then(() => { delete last[id]; refresh(); });
}

export function clearFinished() {
  apiPost("/api/jobs/dismiss", { finished: true }).then(refresh);
}

// Called once by installNotify() (the DOMContentLoaded equivalent). Idempotent.
export function start() {
  if (started) return;
  started = true;
  open = readOpen();
  emit();
  refresh().then(schedule);
}

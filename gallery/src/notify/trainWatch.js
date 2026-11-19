/* notify/trainWatch.js -- a LoRA training run you started says when it finishes or fails,
   once, in the app's normal corner notice (2026-11-18: owner-started job -> notice).

   No new server work and no new endpoint: it reads /api/train/runs, the list the Train
   screens already poll (that route answers from a 10-second cache, so several readers cost
   PixAI one read). It learns about runs two ways --
     * the Train screens hand it every list they read (noteTrainRuns, from useTrainRuns), so a
       run started there is watched from the moment it shows as queued;
     * one light read a little after the app opens, for a run started earlier or elsewhere.
   While anything is watched it looks again every minute (never in a hidden tab). A run that
   leaves the running list is looked up once in the full list and announced by how it ended.
   "Once" holds across tabs and reloads: the ids already announced are kept in this browser.

   Started from installNotify(), like the jobs poll. */
import { apiGet } from "../api.js";
import { show as toastShow } from "./toastStore.js";
import { ended, finishNotice, liveRuns } from "../lib/trainWatchCore.js";

const SEEN_KEY = "mg_train_announced";
const POLL_MS = 60000;
const BOOT_DELAY_MS = 30000;

const watched = new Map();          // run id -> title
let timer = null;
let started = false;

function announced() {
  try { return new Set(JSON.parse(localStorage.getItem(SEEN_KEY) || "[]")); } catch { return new Set(); }
}
function markAnnounced(id) {
  try {
    const ids = [...announced(), id].slice(-50);
    localStorage.setItem(SEEN_KEY, JSON.stringify(ids));
  } catch { /* private mode: once per tab instead */ }
}

function schedule() {
  if (timer || watched.size === 0) return;
  timer = setTimeout(() => {
    timer = null;
    if (typeof document !== "undefined" && document.visibilityState === "hidden") { schedule(); return; }
    apiGet("/api/train/runs?running=1").then((d) => { if (d && !d.error) noteTrainRuns(d); schedule(); });
  }, POLL_MS);
}

function settle(ids) {
  apiGet("/api/train/runs").then((d) => {
    if (!d || d.error) return;                  // keep them; the next look tries again
    const rows = new Map((d.runs || []).map((r) => [String(r.id), r]));
    for (const id of ids) {
      const title = watched.get(id);
      const row = rows.get(id);
      if (row && (row.status === "running" || row.status === "waiting")) continue;
      watched.delete(id);
      const n = finishNotice(row, title);
      if (!n || announced().has(id)) continue;
      markAnnounced(id);
      toastShow(n);
    }
  });
}

/* Every list a Train screen (or this watcher) reads comes through here. */
export function noteTrainRuns(d) {
  if (!d || d.error) return;
  const live = liveRuns(d);
  const gone = ended(watched, live);
  for (const [id, title] of live) watched.set(id, title);
  if (gone.length) settle(gone);
  schedule();
}

export function startTrainWatch() {
  if (started || typeof window === "undefined") return;
  started = true;
  setTimeout(() => {
    apiGet("/api/train/runs?running=1").then((d) => { if (d && !d.error) noteTrainRuns(d); });
  }, BOOT_DELAY_MS);
}

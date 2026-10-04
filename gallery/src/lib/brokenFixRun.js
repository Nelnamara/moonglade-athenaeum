/* The Broken files list's fix run, client side (Session W, W3c / W4c). A MODULE SINGLETON, like
   notify/jobsStore.js: the run is a thread on the server (moonglade_integrity.FixRunner), and
   closing Health must not stop anyone from hearing how it ended -- so the poll lives here, outside
   any component, and the section and the phone screen only subscribe.

   What it does:
     startFix(ids)  POST /api/integrity/fix (one row's Re-download / Rebuild, or Fix all) and poll
                    GET /api/integrity/fix/status until the run ends. The server decides what each
                    row gets and refuses an archive-only row by itself; nothing here can override it.
     stopFix()      Stop: the current file finishes, then the run ends.
     resume(st)     a run already going (the list's `run`, e.g. after a reload): poll it too.
   Every row that finishes OK is stamped in `fixedAt`, so its ✓ FIXED shows for 2 s and then it
   leaves the list. When a run ends, Health's and the list's cached reads are dropped and every
   onRunEnd listener hears it (the list reloads; the shell's toast says the counts).

   It reads and writes nothing else, and it never retries a POST. */

import { apiGet, apiPost } from "../api.js";
import { invalidate } from "../hooks/swrStore.js";

const STATUS = "/api/integrity/fix/status";
export const FIXED_MS = 2000;             // how long a finished row shows ✓ FIXED
const POLL_MS = 600;

let status = null;                        // the server's last answer
let fixedAt = {};                         // media_id -> when it finished OK (this tab's clock)
let seen = 0;                             // results already absorbed
let polling = false;
const subs = new Set();
const enders = new Set();

function csrf() {
  try { return (window.MG_BOOT && window.MG_BOOT.csrf) || ""; } catch { return ""; }
}

export function snapshot() { return { status, fixedAt }; }

function emit() {
  const s = snapshot();
  subs.forEach((fn) => { try { fn(s); } catch { /* a subscriber's own */ } });
}

export function subscribe(fn) {
  subs.add(fn);
  fn(snapshot());
  return () => subs.delete(fn);
}

export function onRunEnd(fn) {
  enders.add(fn);
  return () => enders.delete(fn);
}

export function isRunning() { return !!(status && status.running); }

function ended(st) {
  invalidate(["/api/health", "/api/integrity/broken", "/api/panel/summary"]);
  enders.forEach((fn) => { try { fn(st); } catch { /* a listener's own */ } });
}

function absorb(st) {
  if (!st || st.error) return false;
  const res = st.results || [];
  const now = Date.now();
  for (let i = seen; i < res.length; i++) {
    if (res[i] && res[i].ok) fixedAt = { ...fixedAt, [res[i].media_id]: now };
  }
  seen = res.length;
  const was = !!(status && status.running);
  status = st;
  emit();
  if (was && !st.running) ended(st);
  return true;
}

function poll() {
  if (polling) return;
  polling = true;
  const tick = () => {
    apiGet(STATUS).then((st) => {
      absorb(st);
      if (status && status.running) setTimeout(tick, POLL_MS);
      else polling = false;
    });
  };
  setTimeout(tick, POLL_MS);
}

/* Start a run over `ids`. Resolves to the server's answer ({error} on a refusal, 409 busy). */
export async function startFix(ids) {
  const d = await apiPost("/api/integrity/fix", { csrf: csrf(), ids });
  if (!d || d.error) return d || { error: "Couldn't start the fix." };
  fixedAt = {};
  seen = 0;
  status = null;
  absorb(d);
  if (d.running) poll();
  return d;
}

export function stopFix() {
  return apiPost("/api/integrity/fix/stop", { csrf: csrf() });
}

/* A run the server already has going (seen in the list's `run`): follow it from here. */
export function resume(st) {
  if (!st || !st.running || polling) return;
  seen = (st.results || []).length;
  status = st;
  emit();
  poll();
}

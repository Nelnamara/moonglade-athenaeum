/* notify/jobs.js -- the SPEND-CRITICAL Jobs engine, ported verbatim from static/mg-notify.js's
   Jobs IIFE (no-vanilla campaign, component 6). A MODULE SINGLETON, deliberately outside any
   React lifecycle: Jobs.track's poll loop is what drives a PAID generation's completion callback
   (the download + catalog insert), and it must keep ticking to a terminal phase after the
   launching UI (the Generate dock, a mobile screen) closes or unmounts. Each poll chain is a
   self-perpetuating setTimeout closure holding no component reference -- exactly the property
   that made the vanilla survive the drawer closing, preserved here on purpose.

   SPEND-SAFETY CONTRACT (do not weaken):
   - This module NEVER submits or spends. It GETs /api/task-status and POSTs job METADATA to
     /api/jobs (fire-and-forget, through api.js's apiPost, which never throws). The only retries
     are idempotent READS (again(4000) on a fetch reject) -- a transient network blip keeps
     watching, it never re-submits anything.
   - The task-status poll keeps its OWN fetch rather than riding apiGet: the REJECTION is the
     retry trigger, and api.js's one error rule deliberately turns a dropped read into an
     {error} body, which this loop would read as a non-terminal phase and re-poll at the normal
     cadence instead of the 4s blip floor. Named as an exemption in
     loom/test/request-module-structure.test.js.
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

import { apiPost } from "../api.js";
// From the STORE, not hooks/swrCache.js: this module is a singleton deliberately outside
// any React lifecycle (see the contract above), and swrStore.js imports nothing at all --
// so the spend-critical poller picks up a Map and three functions, not React.
import { invalidate } from "../hooks/swrStore.js";
import { refresh as trayRefresh } from "./jobsStore.js";
import { cadenceFor } from "./pollCadence.js";

const seen = {};

/* Active (non-terminal) tracked polls, keyed by task id -- complements `seen`, which is the
   permanent submit-dedup above and is never cleared. `pending` holds ONLY jobs still being
   polled, each carrying the SINGLE live setTimeout handle and the exact args to resume it.
   INVARIANT: one entry <=> one live timer. That is what lets the visibility handler at the foot
   of this file pull a throttled poll forward without ever creating a second poll loop (it clears
   the timer before refiring), and it is module state -- not a component reference -- so the
   "loop survives the launching UI closing" property at the top of this file is unchanged. */
const pending = {};

function clearPending(id) {
  const p = pending[id];
  if (p && p.timer) clearTimeout(p.timer);
  delete pending[id];
}

export function register(id, label, count) {
  if (!id || seen[id]) return;
  seen[id] = true;
  // count: how many images this ONE task renders (1-4, image-gen only). Omitted by callers
  // that don't know it -- JSON.stringify drops an undefined key, so those registrations are
  // byte-identical to before the param existed.
  apiPost("/api/jobs", { job_id: id, type: "generate", label: label || "Generation", status: "running", count });
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
  /* Re-entry guard: never run two reads for one id at once. This closes the one race the
     visibility handler could otherwise open -- if a throttled timer has ALREADY fired (its
     poll callback sits queued) at the instant wakePending() clears it, clearTimeout cannot
     un-queue it, so both that callback and wakePending's own poll would run. Whichever lands
     second sees `inflight` still set by the first and bails; the first's fetch owns the
     continuation, so exactly one loop survives. A normally-scheduled poll always enters with
     inflight already false (the prior fetch cleared it before scheduling), so this never trips
     the happy path. */
  const existing = pending[id];
  if (existing && existing.inflight) return;
  const t0 = startedAt || Date.now();
  const from = tier || "normal";
  /* Record/refresh this task's resume context for the visibility handler. `inflight` guards it
     from firing a duplicate fetch while this read is still open (that open read reschedules on
     its own settle). `timer` is nulled here because the setTimeout that just fired is spent. */
  const p = pending[id] || (pending[id] = {});
  p.cb = cb; p.t0 = t0; p.timer = null; p.inflight = true;
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
      clearPending(id);              // 6h ceiling: terminal for THIS tab -- stop tracking it
      return;
    }
    if (cb && c.tier !== from && (c.tier === "slow" || c.tier === "stale")) cb(c.tier, d || {});
    /* Store the SINGLE live handle plus the tier this fire would resume at, so the visibility
       handler can reproduce this exact scheduled poll -- only sooner. */
    if (pending[id]) {
      pending[id].nextTier = c.tier;
      pending[id].timer = setTimeout(() => poll(id, cb, t0, c.tier), floorMs ? Math.max(c.ms, floorMs) : c.ms);
    }
  }
  fetch("/api/task-status?task_id=" + encodeURIComponent(id))
    .then((r) => r.json())
    .then((d) => {
      if (pending[id]) pending[id].inflight = false;
      /* Terminal cleanup is atomic with the terminal callback. A flaky host cb thrown
         synchronously (e.g. a broken achievement check on "done") is swallowed, and
         clearPending runs regardless -- clearPending BEFORE trayRefresh, so even a throwing
         refresh cannot leave a live `pending` entry behind. Without this, a throwing done-cb
         skips clearPending, the error falls through to .catch -> again(), and the next poll
         fires cb("done") a SECOND time (a double mg-result). This is a pre-existing hole on
         master; it is closeable here only because `pending` exists and again()'s
         `if (pending[id])` guard then refuses to reschedule a cleared task. A broken UI
         callback must never resurrect a finished, already-collected generation. */
      /* A finished generation moved the library: new art on disk and in the catalog, new
         achievement metrics, a changed Health walk, a changed credit balance. The shared
         READ cache (hooks/swrCache.js) would otherwise hand the next overlay open a
         pre-generation snapshot. This is a PURGE ONLY -- invalidate() drops cached entries
         and issues no request of any kind, which is why it is allowed inside this module at
         all: the spend-safety contract at the top of this file forbids adding any fetch or
         submit here, and dropping a client-side map is neither. */
      if (d.phase === "done") { try { if (cb) cb("done", d); } catch { /* host cb must not resurrect a finished poll */ } invalidate(["/api/achievements", "/api/health", "/api/panel/summary", "/api/your-art", "/api/next/library"]); clearPending(id); trayRefresh(); }
      else if (d.phase === "failed") { try { if (cb) cb("failed", d); } catch { /* as above */ } clearPending(id); trayRefresh(); }
      else { if (cb) cb("running", d); again(d, 0); }
    })
    .catch(() => { if (pending[id]) pending[id].inflight = false; again(null, 4000); });
}

/* Pull a throttled poll forward on tab-refocus. A backgrounded tab's setTimeout is clamped by
   the browser to ~once/minute (frozen harder after a few minutes), so a task that finishes on
   PixAI while you are looking at another tab "lands late" here -- the spinner clears only when
   the throttled timer next fires. On the tab becoming visible again, run each in-flight task's
   NEXT poll NOW: clear its pending (throttled) timer and re-enter poll() with the identical
   (id, cb, t0, tier), so it is byte-for-byte the scheduled poll, only sooner.

   SPEND-SAFE, by the contract at the top of this file: this calls poll() -- a GET of
   /api/task-status -- never register()/track(), so nothing is POSTed and no generation is
   submitted; and it CLEARS the live timer before refiring, so one task can never end up with two
   poll loops (the `pending` one-entry-one-timer invariant). A task whose fetch is already open
   (`inflight`) is skipped -- that open read reschedules itself, and refiring it is the one way to
   double it. Only "visible" transitions act; hiding is ignored (nothing to gain, and a fired
   poll would just be re-throttled). */
function wakePending() {
  if (typeof document !== "undefined"
      && document.visibilityState && document.visibilityState !== "visible") return;
  for (const id in pending) {
    const p = pending[id];
    if (!p || p.inflight || !p.timer) continue;   // open fetch reschedules itself; no timer = nothing to pull
    clearTimeout(p.timer);
    p.timer = null;
    poll(id, p.cb, p.t0, p.nextTier);
  }
}

if (typeof document !== "undefined" && document.addEventListener) {
  document.addEventListener("visibilitychange", wakePending);
}

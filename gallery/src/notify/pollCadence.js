/* notify/pollCadence.js -- the poll TIER TABLE, and nothing else. PURE: no DOM, no fetch, no
   React, no module state, so `node --test` can drive it across the tier edges directly
   (loom/test/poll-cadence.test.js) instead of inferring the schedule from a running poller.

   ONE table, three surfaces. These four thresholds were written for the Loom's pollShot
   (POLL_SLOW_AT_MS / POLL_STALE_AT_MS / POLL_CEILING_MS), then hand-copied into the video
   drawer's own poller under a "KEEP IN SYNC" comment -- the copy that made the drift real.
   The drawer's poller is gone (it rides notify/jobs.js now), so the numbers live here, where
   the one gallery-side poll loop reads them and the drawer imports only CEILING_MS for its
   wording. The Loom's pollShot still carries its own copy: it is a separate bundle with its
   own give-up semantics, and it is out of this seam.

   WHY the cadence steps down at all (softened 2026-07-18, and the reasoning is load-bearing):
   elapsed time alone NEVER ends a render in failure. A 210k-credit video can legitimately take
   an hour. So a long wait only slows the asking and escalates the wording; only a real
   phase==='failed' from the server is a failure. The 6h ceiling is not a verdict either --
   `stalled` says THIS TAB stopped watching, and a reload resumes. */

export const POLL_MS = 3000;                      // normal cadence -- a fresh task, asked every 3s
export const SLOW_AT_MS = 20 * 60 * 1000;         // 20min: was the old hard give-up point
export const SLOW_MS = 20 * 1000;                 // slow-tier cadence
export const STALE_AT_MS = 90 * 60 * 1000;        // 90min: second, slower downshift
export const STALE_MS = 3 * 60 * 1000;            // stale-tier cadence
export const CEILING_MS = 6 * 60 * 60 * 1000;     // 6h: stop polling in THIS tab; the task is untouched

/* cadenceFor(elapsedMs) -> { ms, tier }

   `tier` is one of "normal" | "slow" | "stale" | "stalled"; `ms` is how long to wait before
   asking again. At "stalled" there is no next ask, so `ms` is 0 -- a caller that schedules on
   it anyway is a bug the tier name is meant to catch.

   Boundaries are INCLUSIVE of the slower tier (elapsed >= SLOW_AT_MS is already slow), so a
   threshold is the first instant of the tier it names rather than a millisecond before it. */
export function cadenceFor(elapsedMs) {
  const e = Number(elapsedMs) || 0;
  if (e >= CEILING_MS) return { ms: 0, tier: "stalled" };
  if (e >= STALE_AT_MS) return { ms: STALE_MS, tier: "stale" };
  if (e >= SLOW_AT_MS) return { ms: SLOW_MS, tier: "slow" };
  return { ms: POLL_MS, tier: "normal" };
}

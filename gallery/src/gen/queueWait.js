/* The QUEUE-WAIT readout rule -- one rule, two surfaces.

   PixAI publishes no progress on a task at all. The one honest number it does publish is
   the queue wait its own site shows beside Generate (GET /v2/task/wait-time ->
   moonglade_backup.queue_wait_estimate), recorded ONCE into the job log the first time
   /api/task-status sees a job accepted-but-not-started (moonglade_gallery._note_gen_phase)
   and served to every client on the `eta_seconds` field of /api/jobs. It is a QUEUE wait,
   never a render ETA and never a countdown -- so it is worded as an estimate of the WAIT
   and it must vanish the instant the task leaves the queue.

   The Activity tray has rendered it since 2026-07-25 (notify/ActivityRow.jsx: the .at-eta
   chip). The dock's runs reel showed only the mascot + indeterminate shimmer for the same
   job. This module is the rule both surfaces agree on, extracted and IMPORT-LIGHT (only
   notify/format.js, itself importless) for the same reason hooks/contestSyncFlow.js is:
   RunsReel.jsx is JSX and the node suite cannot import it, so the rule that decides
   whether a figure is shown at all is testable only outside the component.

   The gate is deliberately three separate conditions, none of them a truthiness check:
     · the job is still RUNNING           -- a terminal job is not waiting for anything;
     · `started === false`, never `!started` -- the field is ABSENT on every non-PixAI job
       (panel/cli/delete/import) and on rows written before the phase feature, and absent
       means UNKNOWN, not queued;
     · `eta_seconds` is a finite NUMBER   -- `eta_seconds &&` would collapse a real, honest
       0 ("the queue is empty") into "no estimate". */

import { fmtDuration } from "../notify/format.js";

/* The smallest reel tile (RunsReel's `th`) that can carry the readout without cutting into
   the mascot or truncating the word "wait". MEASURED, not guessed: server-rendered against
   the committed dock.css at every tier the reel uses (dockLayout.js: 132/104/96 normal and
   expanded, 84 and 64 on short windows), "est. 27s wait" needs 51px of the 58px a 96px tile
   leaves and clears the mascot by 2px; an 84px tile leaves 49px and runs into it. Below the
   floor the reel is in its most compressed form and simply says nothing -- a clipped
   "est. 27s w…" would drop the one word that keeps this honest, and the Activity tray
   carries the same figure at full size either way. Same shape as the reel's own
   REEL_MIN_ROOM (gen/dockLayout.js): no room, no render. */
export const WAIT_MIN_TILE = 96;

/* True only for a job PixAI has accepted and no worker has picked up yet. */
export function isQueuedRun(j) {
  return !!j && (j.status || "running") === "running" && j.started === false;
}

/* The readout, or "" when there is nothing honest to say. The wording is the tray's:
   "est. <duration> wait" -- the noun is WAIT, and the word survives every caller. */
export function queueWaitText(j) {
  if (!isQueuedRun(j)) return "";
  const eta = j.eta_seconds;
  if (typeof eta !== "number" || !isFinite(eta)) return "";
  return "est. " + fmtDuration(eta) + " wait";
}

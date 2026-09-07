/* ONE RUNS-ITSELF ROW'S "LAST RAN" (2026-09-06, red team #18).

   THE DISAGREEMENT this closes. A Runs-itself row draws two times from two different
   sources, and they did not agree in the steady state the feature is designed to reach:

     * "next in 12m" comes from schedule.json's own `last_run`, which _living_stamp writes
       on EVERY completed tick, whether the job wrote anything or not.
     * "last ran" came from the Activity ledger alone -- and the published-artwork sweep
       only writes a ledger entry when it CHANGED something. A fifteen-minute heartbeat
       that logged every quiet pass would bury the events that matter under its own noise,
       so that silence is deliberate and correct.

   So a healthy sweep that found nothing new showed "last ran —" beside a live "next in
   12m" on the same row, which reads as broken automation to the owner even though it is
   working exactly as designed. The schedule's own stamp is the honest fallback: it is the
   same fact, recorded by the tick rather than by the job.

   A pure function of the two sources so it can be proven without a browser -- the Panel is
   a React overlay, and this is the one piece of it that is arithmetic rather than markup. */

/* The unix seconds to show in a row's "last ran" cell, or null for "genuinely never".

   `last` is the newest Activity ledger event for this action (or null/undefined when the
   job has never written one); `row` is the saved schedule row. A zero, a blank or a value
   that will not read as a number is not a time, and answers null rather than 1970. */
export function lastRanAt(last, row) {
  const ledger = Number((last || {}).ts);
  if (Number.isFinite(ledger) && ledger > 0) return ledger;
  const stamped = Number((row || {}).last_run);
  if (Number.isFinite(stamped) && stamped > 0) return stamped;
  return null;
}

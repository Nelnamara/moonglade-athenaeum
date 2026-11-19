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

/* THE SYNC META LINE'S "auto" (2026-11-18). Two schedulers can run Sync: the legacy standing
   order (schedule.enabled / action / interval_hours, the Ledger's row) and the living
   library's own Sync row (schedule.jobs, the Runs-itself list). The line under "Sync now"
   read the first alone, so it said "auto off" while the Runs-itself row said Sync was on --
   and the living row WAS running it. This answers the way the server's tick decides: when
   the standing order is on and names Sync it runs it (the Sync row is marked deferred to it),
   otherwise the Sync row does when it is on.

   `schedule` is /api/panel/schedule's answer. Returns {on, every, by}: `every` is the
   cadence in the Runs-itself rows' own words, `by` names the standing order when it is the
   one running it. */
export function fmtCadence(s) {
  const n = Number(s);
  if (!Number.isFinite(n) || n <= 0) return "—";
  if (n < 3600) return Math.round(n / 60) + " min";
  if (n < 86400) { const h = Math.round(n / 3600); return h + (h === 1 ? " hour" : " hours"); }
  const d = Math.round(n / 86400); return d + (d === 1 ? " day" : " days");
}

export function autoSync(schedule) {
  const s = schedule || {};
  const cat = (s.catalog || []).find((c) => c.action === "sync") || {};
  if (cat.deferred || (s.enabled && s.action === "sync")) {
    return { on: true, every: fmtCadence((Number(s.interval_hours) || 6) * 3600), by: "the standing order" };
  }
  const row = (s.jobs || []).find((j) => j.action === "sync");
  if (row && row.enabled) return { on: true, every: fmtCadence(row.interval_s), by: "" };
  return { on: false, every: "", by: "" };
}

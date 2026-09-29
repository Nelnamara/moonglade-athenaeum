/* The moon gauge's rules (Small Calls handoff, L4; DECISIONS 2026-09-28 "The moon gauge fills
   only on a true fraction"). Pure, so loom/test/moon-gauge-core.test.js holds them.

   A gauge is only ever drawn for a TRUE fraction: a count out of a known total (a Folio ladder's
   7 of 10, a Loom board's finished shots) or a percentage the service itself reports (a LoRA
   training run's `progress`). A running generation reports no progress, so it never gets one --
   callers keep their predicted-wait text there. Every reader below answers null for anything
   that is not a real fraction, and the component draws nothing for null. */

// The four places the handoff sizes it (px): Folio 16 · runs rows 16 · training strip 18 · phone 14.
export const GAUGE_SIZES = Object.freeze({ folio: 16, runs: 16, strip: 18, phone: 14 });

function finite(n) {
  return typeof n === "number" && Number.isFinite(n);
}

/* done / total -> a fraction in [0, 1], or null when the total is unknown, zero or negative
   (there is no fraction of nothing), or either side is not a number. */
export function fractionOf(done, total) {
  const d = typeof done === "string" && done.trim() !== "" ? Number(done) : done;
  const t = typeof total === "string" && total.trim() !== "" ? Number(total) : total;
  if (!finite(d) || !finite(t) || t <= 0) return null;
  return Math.min(1, Math.max(0, d / t));
}

/* A reported percentage (0-100, PixAI's training `extra.progress`) -> a fraction, or null when
   the service did not report one. */
export function fractionFromPercent(pct) {
  if (pct === null || pct === undefined || pct === "") return null;
  const n = Number(pct);
  if (!Number.isFinite(n)) return null;
  return Math.min(1, Math.max(0, n / 100));
}

/* The phase frame nearest the fraction: frame 0 is a new moon, frames-1 full. The art's strip
   is drawn so frame k is exactly k/(frames-1) lit (build_moon_gauge.py). */
export function moonFrame(fraction, frames) {
  const n = Math.max(2, Math.floor(frames || 2));
  if (!finite(fraction)) return 0;
  const f = Math.min(1, Math.max(0, fraction));
  return Math.round(f * (n - 1));
}

/* "new" at 0 (drawn as a new-moon outline), "full" at 1 (a full moon with the lavender glow),
   "wax" between. A fraction that rounds to the full frame but is not 1 stays "wax": the glow
   means finished, never "nearly". */
export function gaugePhase(fraction) {
  if (!finite(fraction) || fraction <= 0) return "new";
  if (fraction >= 1) return "full";
  return "wax";
}

/* The exact reading beside the moon: whole percent, never rounded up to 100 before it is. */
export function percentText(fraction) {
  if (!finite(fraction)) return "";
  const f = Math.min(1, Math.max(0, fraction));
  const p = f >= 1 ? 100 : Math.min(99, Math.floor(f * 100));
  return p + "%";
}

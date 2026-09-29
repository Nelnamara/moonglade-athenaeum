/* =========================================================================
   loom-bed-core.js — THE MUSIC BED (P3), as pure data and timing math.

   Session P, Stage B1 (NOTES P3; Loom Handoff.dc.html section A's bed row and section B's
   P3 prose; BUILD-w5-p §5.5; rulings 8 and 15; review F18/F19). One local audio file per
   storyboard, never uploaded, never sent to PixAI:

     project.bed = {file, name, dur, db: -8, fadeIn: 2, fadeOut: 3}

   `file` is the content-addressed name the server stored it under
   (out_dir/loom/_beds/<account>/<sha1>.<ext>); `name` is what the owner's file was called
   (display only); `dur` its length in seconds (ffprobe, else the <audio> element's).
   The field is ADDITIVE: absent on every board saved before this build, and nothing writes it
   on open. Picking, levelling and removing it are board edits the owner makes.

   The rules the page states, in one place so Play (WebAudio) and ⇧ Render (ffmpeg, the
   server's twin in moonglade_gallery.loom_bed_audio_graph) cannot disagree:
     - level: −24…0 dB, default −8
     - fades: 2 s in, 3 s out
     - ducking: −12 dB MORE under a shot that carries its own audio (hasOwnAudio below)
     - a bed longer than the cut is cut to the cut, with the out-fade ending at the cut's end;
       a shorter one ends where it ends (its own out-fade) and never loops.

   Same discipline as loom-core.js / loom-takes-core.js: NO React, no DOM, no window, no
   fetch, no timers. loom/test/loom-no-auto-render.test.js pins that it imports only
   loom-takes-core.js and names no render path.
   ========================================================================= */

import { selectedTakeView } from "./loom-takes-core.js";

export const BED_DB_DEFAULT = -8;
export const BED_DB_MIN = -24;
export const BED_DB_MAX = 0;
export const BED_FADE_IN = 2;
export const BED_FADE_OUT = 3;
export const BED_DUCK_DB = -12;
/** The server's own cap (moonglade_gallery.LOOM_BED_MAX_BYTES). The client checks it first so
 *  a too-big file is refused before a byte is sent; the server enforces it regardless. */
export const BED_MAX_BYTES = 50 * 1024 * 1024;
/** A stored bed's name: the sha1 of its bytes and the sniffed type. The server's
 *  LOOM_BED_FILE_RE is the same pattern (tests/test_loom_p_routes.py compares them). */
export const BED_FILE_RE = /^[0-9a-f]{40}\.(mp3|wav|m4a|aac|ogg|flac)$/;

const num = (v) => { const n = Number(v); return Number.isFinite(n) ? n : null; };

/** The level slider's value, clamped to −24…0 and whole dB. Junk -> the default. */
export const clampBedDb = (v) => {
  const n = v == null || v === "" ? null : num(v);
  if (n == null) return BED_DB_DEFAULT;
  return Math.max(BED_DB_MIN, Math.min(BED_DB_MAX, Math.round(n)));
};

/** A freshly picked bed. `keepDb` carries the level over when a bed is replaced. */
export const makeBed = ({ file, name, dur } = {}, keepDb) => ({
  file: String(file || ""),
  name: String(name || "").slice(0, 120) || "music bed",
  dur: num(dur) != null && num(dur) > 0 ? num(dur) : null,
  db: keepDb != null ? clampBedDb(keepDb) : BED_DB_DEFAULT,
  fadeIn: BED_FADE_IN,
  fadeOut: BED_FADE_OUT,
});

/** The board's bed, or null when there is none (or it names no playable file). A view:
 *  never writes. The fades are the page's fixed 2 s / 3 s whatever a board carries. */
export const bedOf = (project) => {
  const b = project && project.bed;
  if (!b || typeof b !== "object" || !BED_FILE_RE.test(String(b.file || ""))) return null;
  return { file: String(b.file), name: String(b.name || "music bed"), dur: num(b.dur) > 0 ? num(b.dur) : null,
    db: clampBedDb(b.db == null ? BED_DB_DEFAULT : b.db), fadeIn: BED_FADE_IN, fadeOut: BED_FADE_OUT };
};

/** "1:42" for the bed button. */
export const bedClock = (sec) => {
  const n = num(sec);
  if (n == null || n <= 0) return "";
  const s = Math.round(n);
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
};

/** The dB label the page shows: "−8 dB" with a real minus sign. */
export const dbLabel = (db) => {
  const d = clampBedDb(db);
  return (d < 0 ? "−" + Math.abs(d) : String(d)) + " dB";
};

/**
 * OWN AUDIO -- the ONE definition (P3: "shots with their own audio (R2V with an audio ref, or
 * V2V source audio)", plus a take rendered with Generate audio on). It describes the ★ take:
 * what that take was rendered with (its settings snapshot) when it recorded one, else the
 * card's own fields (a legacy or attached take recorded none). The bed ducks under it.
 *   - the take was rendered with generate_audio on
 *   - V2V: the source video's sound comes through
 *   - R2V with an @audio reference: an audio-kind shot reference, or an audio cast member
 */
export const hasOwnAudio = (card, project) => {
  if (!card) return false;
  const v = selectedTakeView(card);
  const s = (v && v.settings) || null;
  const mode = String((s && s.mode) || card.mode || "");
  const audioGen = s ? !!s.audioGen : !!card.audioGen;
  if (audioGen) return true;
  if (mode === "V2V") return true;
  if (mode !== "R2V") return false;
  const refs = (s ? s.refs : card.refs) || [];
  if (refs.some((r) => r && r.kind === "audio")) return true;
  const cast = (s ? s.cast : card.cast) || [];
  const assets = (project && project.assets) || [];
  return assets.some((a) => a && a.kind === "audio" && cast.includes(a.id));
};

/**
 * The cut the bed plays under: every rendered shot in board order with its span (the same
 * span the local cut uses: trimOut ?? actualDur ?? duration ?? 8, minus trimIn, at least
 * 0.1 s -- loom-mutations.js buildExportClips), where it starts in the cut, and whether it has
 * its own audio. Unrendered shots are skipped, as Play and ⇧ Render skip them.
 * `entries` are loom-core.js flat(project) entries.
 */
export const cutSegments = (entries, project) => {
  let at = 0;
  const out = [];
  (entries || []).forEach((e) => {
    const c = e && e.c;
    if (!c || !c.resultMid) return;
    const dur = num(c.actualDur) || num(c.duration) || 8;
    const cin = num(c.trimIn) || 0;
    const cout = c.trimOut != null && num(c.trimOut) != null ? num(c.trimOut) : dur;
    const span = Math.max(0.1, cout - cin);
    out.push({ id: c.id, code: e.code, start: at, end: at + span, span, ownAudio: hasOwnAudio(c, project) });
    at += span;
  });
  return out;
};

/**
 * bedPlan(segments, bed) -> {cutLen, bedLen, db, duckDb, fadeIn, fadeOut, windows} | null
 *   cutLen   the cut's length
 *   bedLen   how long the bed plays: min(bed length, cut length); the whole cut when the
 *            bed's length is unknown
 *   windows  [{start, end}] where the bed ducks (a shot with its own audio), clipped to bedLen
 * The out-fade ends at bedLen: the cut's end for a long bed, the bed's own end for a short one.
 * Fades never overlap: on a very short bed each is scaled back to half its length.
 */
export const bedPlan = (segments, bed) => {
  if (!bed) return null;
  const segs = segments || [];
  const cutLen = segs.length ? segs[segs.length - 1].end : 0;
  if (!(cutLen > 0)) return null;
  const bd = num(bed.dur);
  const bedLen = bd != null && bd > 0 ? Math.min(bd, cutLen) : cutLen;
  const fadeIn = Math.min(BED_FADE_IN, bedLen / 2);
  const fadeOut = Math.min(BED_FADE_OUT, bedLen / 2);
  const windows = [];
  segs.forEach((s) => {
    if (!s.ownAudio) return;
    const a = s.start, b = Math.min(s.end, bedLen);
    if (b <= a) return;
    const last = windows[windows.length - 1];
    if (last && Math.abs(last.end - a) < 1e-9) last.end = b;      // adjacent shots: one window
    else windows.push({ start: a, end: b });
  });
  return { cutLen, bedLen, db: clampBedDb(bed.db), duckDb: BED_DUCK_DB, fadeIn, fadeOut, windows };
};

export const dbToGain = (db) => Math.pow(10, db / 20);
const ducked = (plan, t) => plan.windows.some((w) => t >= w.start && t < w.end);
const fadeAt = (plan, t) => {
  if (t < 0 || t >= plan.bedLen) return 0;
  const fin = plan.fadeIn > 0 ? Math.min(1, t / plan.fadeIn) : 1;
  const fout = plan.fadeOut > 0 ? Math.min(1, (plan.bedLen - t) / plan.fadeOut) : 1;
  return Math.max(0, Math.min(fin, fout));
};

/** The bed's level at cut time t, in dB (level, plus the duck where it ducks), or null when
 *  the bed is silent there (before 0 or after it ended). Fades are separate (bedGainAt). */
export const bedDbAt = (plan, t) => {
  if (!plan || t < 0 || t >= plan.bedLen) return null;
  return plan.db + (ducked(plan, t) ? plan.duckDb : 0);
};

/** The bed's linear gain at cut time t: level and duck, times the fade envelope. 0 outside. */
export const bedGainAt = (plan, t) => {
  const db = bedDbAt(plan, t);
  if (db == null) return 0;
  return dbToGain(db) * fadeAt(plan, t);
};

/**
 * The gain automation from cut time `startAt` on, for WebAudio: [{t, v}] where each point is
 * either reached by a LINEAR ramp from the one before, or (`step:true`) set instantly (a duck
 * boundary). Times are cut seconds; the player maps them onto its AudioContext clock.
 * Linear in amplitude, like ffmpeg's afade (its default "tri" curve), so Play and ⇧ Render
 * shape the fades the same way.
 */
export const bedAutomation = (plan, startAt = 0) => {
  if (!plan) return [];
  const t0 = Math.max(0, num(startAt) || 0);
  if (t0 >= plan.bedLen) return [{ t: t0, v: 0, step: true }];
  const marks = new Set([t0, plan.fadeIn, plan.bedLen - plan.fadeOut, plan.bedLen]);
  plan.windows.forEach((w) => { marks.add(w.start); marks.add(w.end); });
  const times = Array.from(marks).filter((t) => t >= t0 && t <= plan.bedLen).sort((a, b) => a - b);
  const eps = 1e-6;
  const out = [{ t: t0, v: bedGainAt(plan, t0), step: true }];
  for (let i = 1; i < times.length; i++) {
    const t = times[i];
    // The value arriving at t (the left limit) is reached by a ramp; a duck boundary then
    // steps to the value on its right.
    const left = t >= plan.bedLen ? 0 : dbToGain(plan.db + (ducked(plan, t - eps) ? plan.duckDb : 0)) * fadeAt(plan, t);
    out.push({ t, v: left });
    const right = bedGainAt(plan, t);
    if (Math.abs(right - left) > 1e-9) out.push({ t, v: right, step: true });
  }
  return out;
};

/**
 * The waveform the bed row draws, from the real file: a decoded channel's samples reduced to
 * `buckets` peaks (max |sample| per bucket), normalised to 0…1. Done once per decode; the
 * drawing then only looks peaks up (peakAt), so a redraw never re-decodes.
 */
export const peaksToBuckets = (samples, buckets) => {
  const n = Math.max(1, Math.floor(buckets) || 1);
  const len = samples ? samples.length : 0;
  const out = new Array(n).fill(0);
  if (!len) return out;
  const per = len / n;
  for (let i = 0; i < n; i++) {
    const a = Math.floor(i * per), b = Math.min(len, Math.max(a + 1, Math.floor((i + 1) * per)));
    let m = 0;
    for (let k = a; k < b; k++) { const v = Math.abs(samples[k]); if (v > m) m = v; }
    out[i] = m;
  }
  const top = out.reduce((m, v) => Math.max(m, v), 0);
  return top > 0 ? out.map((v) => v / top) : out;
};

/** The peak for bed second `t` out of a whole-file peak list spanning `bedDur` seconds. */
export const peakAt = (peaks, bedDur, t) => {
  if (!peaks || !peaks.length || !(bedDur > 0) || t < 0 || t >= bedDur) return 0;
  return peaks[Math.min(peaks.length - 1, Math.floor((t / bedDur) * peaks.length))] || 0;
};

/** The status line under the bed row when Play is not running (the page's words). */
export const cutStatusLine = (entries, segments) => {
  const all = (entries || []).length;
  const segs = segments || [];
  if (!segs.length) return "nothing rendered yet";
  const len = segs[segs.length - 1].end;
  const skipped = all - segs.length;
  return "cut length " + len.toFixed(1) + " s" + (skipped > 0 ? " · " + skipped + " unrendered skipped" : "");
};

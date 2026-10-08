/* =========================================================================
   loom-edl-core.js — THE EDITOR HANDOFF EXPORT (P4), as a pure plan.

   Session P, Stage B1 (NOTES P4; Loom Handoff.dc.html's Export ▾ → "Edit decision list .edl +
   .csv" and its EDL panel; section B's P4 prose; BUILD-w5-p §5.1; rulings 6, 7, 8; review F9
   and N2). One zip, built by POST /api/loom/export-edl from what this plans:

     <board>.edl   CMX3600 at 24 fps NON-DROP. Each rendered shot is one V event whose source
                   is its ★ take's clip and whose in/out are that take's trims (a split half is
                   its own event and its own file). Source timecode runs from 00:00:00:00
                   (generated clips carry none, ruling 6); record from 01:00:00:00, sequential.
     <board>.csv   one row per event: order,code,title,take,file,in,out,duration,mode,prompt
     the clips     named {code}_t{take}.mp4 -- A01_t2.mp4 (the code with its "·" removed,
                   ruling 7)
     the bed       when the board has one (ruling 8), as the A event's file

   The ★ take is read through selectedTakeView (review F9): the card's mirror fields are
   authoritative for the selected take, so the EDL uses exactly the trims Play and the local
   cut use -- never a stored copy that an Edit Bay trim has since moved past.

   FRAMES ARE ROUNDED ONCE PER BOUNDARY. A shot's source in and out become whole frames; its
   length is out − in in frames; the record track is the running sum of those whole lengths.
   So record times can never drift, however many shots, and every record out is the next
   record in.

   REELS (ruling 7, review N2). `A01_T2` when it fits CMX3600's 8 characters AND is unique in
   this export; otherwise a per-export fallback `R001`, `R002`… -- never a truncation, which
   is how AA100_T12 and AA100_T1 would both have become "AA100_T1" and relinked the wrong clip.
   Every event names its real file on a `* FROM CLIP NAME:` line.

   Same discipline as the other pure modules: NO React, no DOM, no window, no fetch. It
   imports only loom-core.js and loom-takes-core.js (loom-no-auto-render.test.js pins that).
   ========================================================================= */

import { flat, effectivePrompt } from "./loom-core.js";
import { selectedTakeView } from "./loom-takes-core.js";

export const EDL_FPS = 24;
/** Record time starts at one hour, the usual CMX3600 convention (ruling 6). */
export const EDL_RECORD_START = 3600;
/** A clip's name inside the zip. The server validates every name against the same pattern
 *  (moonglade_gallery.LOOM_EDL_CLIP_RE; dev/tests/test_loom_p_routes.py compares the two). */
export const EDL_CLIP_FILE_RE = /^[A-Za-z0-9]{1,8}_t\d{1,4}\.mp4$/;
/** The bed's name inside the zip (moonglade_gallery.LOOM_EDL_BED_NAME_RE, the same pattern). */
export const EDL_BED_NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.(mp3|wav|m4a|aac|ogg|flac)$/;
export const CSV_HEADER = "order,code,title,take,file,in,out,duration,mode,prompt";

const EOL = "\r\n";
const num = (v) => { const n = Number(v); return Number.isFinite(n) ? n : null; };

/** "A·01" -> "A01": the shot code, ASCII letters and digits only. */
export const codeAscii = (code) => String(code || "").replace(/[^A-Za-z0-9]/g, "");

/** Plain printable ASCII: accents folded, anything else a space, runs collapsed. */
export const asciiText = (s) => String(s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "")
  .replace(/[^\x20-\x7E]/g, " ").replace(/\s+/g, " ").trim();

/** The board's name as the export's file stem and the panel's label: "moonwell-ep1". */
export const boardSlug = (name) => {
  const s = asciiText(name).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48)
    .replace(/-+$/, "");
  return s || "storyboard";
};

/** Seconds -> whole frames, rounded once. */
export const framesOf = (sec, fps = EDL_FPS) => Math.max(0, Math.round((num(sec) || 0) * fps));

/** Whole frames -> HH:MM:SS:FF, non-drop. */
export const timecode = (frames, fps = EDL_FPS) => {
  const f = Math.max(0, Math.round(num(frames) || 0));
  const hh = Math.floor(f / (fps * 3600));
  const mm = Math.floor(f / (fps * 60)) % 60;
  const ss = Math.floor(f / fps) % 60;
  const ff = f % fps;
  return [hh, mm, ss, ff].map((n) => String(n).padStart(2, "0")).join(":");
};

/** Frames -> seconds for the CSV, three decimals (a 24 fps frame is 0.041666… s). */
const secs = (frames, fps) => (frames / fps).toFixed(3);

/**
 * Reels for a list of {ascii, n}: `${ascii}_T${n}` when it fits 8 characters and no other
 * event in this export asks for the same one; otherwise the next free `R001`… (review N2).
 */
export const assignReels = (items) => {
  const want = (items || []).map((it) => codeAscii(it.ascii || it.code) + "_T" + it.n);
  const count = {};
  want.forEach((w) => { count[w] = (count[w] || 0) + 1; });
  const used = new Set(want.filter((w) => w.length <= 8 && count[w] === 1));
  let k = 0;
  const next = () => {
    let r;
    do { k += 1; r = "R" + String(k).padStart(3, "0"); } while (used.has(r));
    used.add(r);
    return r;
  };
  return want.map((w) => (w.length <= 8 && count[w] === 1 ? w : next()));
};

/** One CSV field, RFC 4180: quoted when it holds a comma, a quote or a line break. */
export const csvField = (v) => {
  const s = v == null ? "" : String(v);
  return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
};

/** The bed's name inside the zip: the owner's own file name made ASCII, with the stored
 *  type's extension. Falls back to "music_bed.<ext>". */
export const bedZipName = (bed) => {
  if (!bed || !bed.file) return "";
  const ext = String(bed.file).split(".").pop();
  const stem = asciiText(String(bed.name || "").replace(/\.[A-Za-z0-9]{1,5}$/, ""))
    .replace(/\s+/g, "_").replace(/[^A-Za-z0-9_.-]/g, "").replace(/^[^A-Za-z0-9]+/, "").slice(0, 48);
  const name = (stem || "music_bed") + "." + ext;
  return EDL_BED_NAME_RE.test(name) ? name : "music_bed." + ext;
};

/**
 * edlPlan(project, {bed, name}) -> {edl, csv, clips:[{mid, file}], skipped, events, slug,
 *                                   bedName, cutFrames}
 *   bed   the board's bed (loom-bed-core.js bedOf(project)) or null
 *   name  the board's name, when the caller has a better one than project.name
 */
export const edlPlan = (project, opts = {}) => {
  const fps = EDL_FPS;
  const entries = project && Array.isArray(project.acts) ? flat(project) : [];
  const title = asciiText((opts && opts.name) || (project && project.name) || "Storyboard").toUpperCase().slice(0, 70) || "STORYBOARD";
  const slug = boardSlug((opts && opts.name) || (project && project.name));
  const skipped = [];
  const rows = [];
  entries.forEach((e) => {
    const v = selectedTakeView(e.c);
    if (!v || !v.mid) { skipped.push(e.code); return; }
    const dur = num(v.dur) || num(e.c.duration) || 8;   // v.dur: the card's length when known (> 0), else the take's
    const tin = num(v.trimIn) || 0;
    const tout = v.trimOut != null && num(v.trimOut) != null ? num(v.trimOut) : dur;
    const inF = framesOf(tin, fps);
    const outF = Math.max(inF + 1, framesOf(tout, fps));
    const s = v.settings || null;
    rows.push({ e, v, ascii: codeAscii(e.code), n: v.n, inF, outF, lenF: outF - inF,
      mode: String((s && s.mode) || e.c.mode || ""),
      prompt: String((s && s.sentPrompt) || effectivePrompt(e.c) || "") });
  });
  const reels = assignReels(rows.map((r) => ({ ascii: r.ascii, n: r.n })));
  const lines = ["TITLE: " + title, "FCM: NON-DROP FRAME", ""];
  const csv = [CSV_HEADER];
  const clips = [];
  let rec = EDL_RECORD_START * fps;
  rows.forEach((r, i) => {
    const reel = reels[i];
    const file = (r.ascii.length >= 1 && r.ascii.length <= 8 ? r.ascii : reel) + "_t" + r.n + ".mp4";
    const recIn = rec, recOut = rec + r.lenF;
    rec = recOut;
    lines.push(String(i + 1).padStart(3, "0") + "  " + reel.padEnd(8) + " V     C        "
      + timecode(r.inF, fps) + " " + timecode(r.outF, fps) + " " + timecode(recIn, fps) + " " + timecode(recOut, fps));
    lines.push("* FROM CLIP NAME: " + file);
    const t = asciiText(r.e.c.title).toUpperCase();
    if (t) lines.push("* COMMENT: " + t);
    csv.push([i + 1, r.e.code, r.e.c.title || "", r.n, file, secs(r.inF, fps), secs(r.outF, fps),
      secs(r.lenF, fps), r.mode, r.prompt].map(csvField).join(","));
    clips.push({ mid: String(r.v.mid), file });
  });
  const cutFrames = rec - EDL_RECORD_START * fps;
  if (skipped.length) lines.push("* SKIPPED (no render): " + skipped.join(" "));
  const bed = opts && opts.bed && opts.bed.file ? opts.bed : null;
  const bedName = bed ? bedZipName(bed) : "";
  if (bed && cutFrames > 0) {
    const bd = num(bed.dur);
    const bedF = bd != null && bd > 0 ? Math.min(framesOf(bd, fps), cutFrames) : cutFrames;
    const recIn = EDL_RECORD_START * fps;
    lines.push(String(rows.length + 1).padStart(3, "0") + "  " + "BED".padEnd(8) + " A     C        "
      + timecode(0, fps) + " " + timecode(bedF, fps) + " " + timecode(recIn, fps) + " " + timecode(recIn + bedF, fps));
    lines.push("* FROM CLIP NAME: " + bedName);
    lines.push("* LEVEL " + (Number(bed.db) || 0) + " DB");
    lines.push("* COMMENT: MUSIC BED, FADE 2 S IN AND 3 S OUT, DUCKS -12 DB UNDER SHOTS WITH THEIR OWN AUDIO");
  }
  return {
    edl: lines.join(EOL) + EOL,
    csv: csv.join(EOL) + EOL,
    clips, skipped, events: rows.length, slug, bedName: bed && cutFrames > 0 ? bedName : "", cutFrames, fps,
  };
};

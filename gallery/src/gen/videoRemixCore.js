/* videoRemixCore.js -- the PURE mapping behind "↺ Remix for videos" (SCOPE_2026-08-17 §2).
   Given a catalog row and the /api/video-task-params/<task_id> read, it produces the prefill
   object <VideoDrawer>.prefill() consumes (gen/videoDrawerCore.applyPrefill) plus the amber
   disclosure notes (§2.4). No DOM, no React, no fetch -- so the loom node-tests exercise the
   real mapping matrix (§2.2) directly.

   Why a catalog row AND a task read: the row alone recovers engine + duration + prompt and
   little else (r2v tasks carry no video_model/video_mode/source_media_id column -- §2.2), so
   the task read is the feature. But the row is the fallback when the task can't be read, and
   it is the ONLY place a numeric engine id lands (`--sync-videos` writes the numeric modelId,
   the dock writes the name -- §2.2), so the row still feeds the engine resolve. */

import { MODELS, MODEL_MAXDUR, snapDuration } from "./videoDrawerCore.js";

// Numeric top-level `modelId` -> engine NAME. Mirror of moonglade_backup.VIDEO_MODELS (the
// five engines that publish a numeric id; v3.0.1 / v2.7 have none). A catalog-only remix, or
// a task whose engine field is blank, falls back to the row's model_id, which `--sync-videos`
// records as this number rather than the "v4.0.1"-style name the drawer speaks.
export const NUMERIC_TO_NAME = {
  "2003969750675682808": "v4.0.1",
  "2003968021137101826": "v4.0",
  "1961182207978260675": "v3.2",
  "2014412117889628958": "v3.0.2",
  "1919508300549460046": "v3.0",
};
const MODEL_VALUES = new Set(MODELS.map((m) => m.value));

// A raw engine field (a "v4.0.1" name, a numeric modelId, or something the roster has dropped)
// resolved to the name the drawer speaks. Unknown values pass through unchanged so the caller
// can disclose "engine no longer in the roster" rather than silently substituting one.
export function resolveEngine(raw) {
  const v = String(raw == null ? "" : raw).trim();
  if (!v) return "";
  if (MODEL_VALUES.has(v)) return v;
  if (NUMERIC_TO_NAME[v]) return NUMERIC_TO_NAME[v];
  return v;
}

// A media id we hold -> the {media_id, thumb} shape refItem accepts.
function libRef(mid) {
  return { media_id: String(mid), thumb: "/thumbs/" + String(mid) + ".jpg" };
}

// Push the clamp disclosure if the recipe's duration is above the resolved engine's cap.
// applyModelGating (applyPrefill's LAST step) does the actual clamp; this only NAMES it, so a
// 15s V4.0 shot remixed onto a 10s-cap engine reads "duration lowered to the engine's max".
function clampNote(prefill, engine, notes) {
  const maxDur = MODEL_MAXDUR[engine] || 10;
  if (prefill.duration != null && prefill.duration > maxDur) {
    notes.push("duration lowered to the engine's max");
  }
}

/* (row, taskParams) -> { prefill, notes }. `taskParams` is the /api/video-task-params body, or
   null / {error} when the task couldn't be read -- in which case the recipe comes from the
   catalog row alone, disclosed. Only keys actually recovered are set on `prefill`, so
   applyPrefill leaves every un-recovered field at the drawer's default. */
export function videoRemixFromRow(row, taskParams) {
  row = row || {};
  const notes = [];
  const prefill = {};

  // ---- CATALOG-ONLY: the task record is unreadable (network, delisted, chat) --------------
  if (!taskParams || taskParams.error) {
    const engine = resolveEngine(row.video_model || row.model_id);
    if (engine) {
      if (!MODEL_VALUES.has(engine)) notes.push("engine no longer in the roster");
      prefill.video_model = engine;
    }
    prefill.mode = "i2v";                       // shot mode is not a catalog column (§2.2)
    if (row.video_duration) prefill.duration = snapDuration(row.video_duration);
    if (row.video_mode) prefill.quality = row.video_mode;   // i2vPro.mode column, when present
    if (row.source_media_id) prefill.images = [libRef(row.source_media_id)];
    if (row.negative_prompt) prefill.negative = row.negative_prompt;
    prefill.prompt = row.prompt_full || row.prompt_preview || "";
    clampNote(prefill, engine, notes);
    notes.push("no task record — recipe from the catalog only");
    notes.push("camera / audio / channel unknown");
    return { prefill, notes };
  }

  // ---- FULL: the task read is authoritative ----------------------------------------------
  const tp = taskParams;
  const engine = resolveEngine(tp.video_model || row.video_model || row.model_id);
  if (engine) {
    if (!MODEL_VALUES.has(engine)) notes.push("engine no longer in the roster");
    prefill.video_model = engine;
  }
  prefill.mode = tp.kind || "i2v";
  const dur = (tp.duration != null && tp.duration !== "") ? tp.duration : row.video_duration;
  if (dur != null && dur !== "") prefill.duration = snapDuration(dur);
  if (tp.quality) prefill.quality = tp.quality;
  prefill.camera = tp.camera || "unset";
  prefill.audio = !!tp.audio;
  if (tp.audio_language) prefill.audio_language = tp.audio_language;
  prefill.prompt_helper = !!tp.prompt_helper;
  if (tp.negative) prefill.negative = tp.negative;
  prefill.is_private = !!tp.is_private;
  prefill.prompt = tp.prompt || row.prompt_full || row.prompt_preview || "";

  // Every branch writes its ref keys UNCONDITIONALLY -- an empty list is the complete,
  // authoritative "no refs" for this shot, and applyPrefill CLEARS the matching bank from it
  // (images -> applySetRefs([]) empties the primary bank; video_refs:[] empties vidSlots;
  // audio_ref:null empties audSlot). Setting them only when something was recovered let the
  // PREVIOUS remix's tiles survive into THIS shot's PAID payload when the new clip's refs were
  // uploads (in_lib:false) -- the wrong-shot spend bug the flf branch's positional-null already
  // avoided; the r2v/i2v branches just didn't pass the empties. (Adversarial, 2026-08-22.)
  if (tp.kind === "r2v") {
    // referenceImageMediaIds may be upload ids PixAI won't hand back as library media (issue
    // #7, unsettled -- §2.5). Restore the refs we actually hold; disclose the rest rather than
    // wiring an id we can't resolve into a paid submission.
    const imgs = (tp.image_refs || []).filter((x) => x && x.in_lib).map((x) => libRef(x.media_id));
    prefill.images = imgs;   // empty -> clears the r2v image bank
    if ((tp.image_refs || []).some((x) => x && !x.in_lib)) notes.push("reference images were uploads — pick them again");
    const vids = (tp.video_refs || []).filter((x) => x && x.in_lib).map((x) => libRef(x.media_id));
    prefill.video_refs = vids;   // empty -> clears vidSlots
    if ((tp.video_refs || []).some((x) => x && !x.in_lib)) notes.push("reference videos were uploads — pick them again");
    const aud = (tp.audio_refs || []).find((x) => x && x.in_lib);
    prefill.audio_ref = aud ? { media_id: String(aud.media_id), filename: "audio ref" } : null;   // null -> clears audSlot
    if (!aud && (tp.audio_refs || []).length) notes.push("the audio reference was an upload — pick it again");
  } else if (tp.kind === "flf") {
    // Positional [start, end]; a null is a deliberate empty slot. Written unconditionally so a
    // frame-less flf remix still clears both slots rather than inheriting the prior shot's.
    const start = (tp.start && tp.start.in_lib) ? libRef(tp.start.media_id) : null;
    const end = (tp.end && tp.end.in_lib) ? libRef(tp.end.media_id) : null;
    if (tp.start && !tp.start.in_lib) notes.push("start frame isn't in your library");
    if (tp.end && !tp.end.in_lib) notes.push("end frame isn't in your library");
    prefill.images = [start, end];
  } else {   // i2v: start frame only. [] (never [null]) clears -- an empty list won't call refItem.
    prefill.images = (tp.start && tp.start.in_lib) ? [libRef(tp.start.media_id)] : [];
    if (tp.start && !tp.start.in_lib) notes.push("start frame isn't in your library");
  }

  clampNote(prefill, engine, notes);
  return { prefill, notes };
}

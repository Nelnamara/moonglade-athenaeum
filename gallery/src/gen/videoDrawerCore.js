/* videoDrawerCore.js -- the pure data + helpers of the video Generate drawer, ported VERBATIM
   from static/mg-generate-drawer.js (no-vanilla campaign, component 7 -- the last one). No
   DOM/React dependency, exported individually so the loom node-tests import the real values +
   functions instead of regex-extracting them from a vanilla file. The <VideoDrawer> React
   component consumes all of these. */

// Full site roster, in PixAI's real model-picker order -- newest first, V2.7 last
// (private/VIDEO_MODELS.md, owner screenshots 2026-07-18). All seven are selectable.
export const MODELS = [
  { value: "v4.0", label: "V4.0 Preview", caps: ["multi-ref", "audio", "15s", "top quality", "~2.5× cost"] },
  { value: "v4.0.1", label: "V4.0 Lite Preview", caps: ["multi-ref", "audio", "15s", "end-frame"] },
  { value: "v3.2", label: "V3.2", caps: ["audio", "prompt-following"] },
  { value: "v3.0.2", label: "V3.0 Lite", caps: ["complex motion", "cheap"] },
  { value: "v3.0", label: "V3.0 (High Consistency)", caps: ["high-consistency", "action presets", "start/end"] },
  { value: "v3.0.1", label: "V3.0 Flash", caps: ["multi-shot", "hires", "fastest", "no card"] },
  { value: "v2.7", label: "V2.7 (High Dynamics)", caps: ["camera moves", "dynamic", "no card"] },
];

// Per-model reference/frame-mode gating -- which of the i2v/flf/r2v vmode buttons a given model
// supports (private/GENERATOR_SURFACE.md, owner screenshots 2026-07-18): Multi-Reference (r2v)
// is exclusive to the V4.0 pair; First+Last (flf) is on the three V3.0-gen models; V2.7 and V3.0
// Flash are First Frame only.
export const MODEL_VMODES = {
  "v4.0": ["i2v", "flf", "r2v"],
  "v4.0.1": ["i2v", "flf", "r2v"],
  "v3.2": ["i2v", "flf"],
  "v3.0.2": ["i2v", "flf"],
  "v3.0": ["i2v", "flf"],
  "v3.0.1": ["i2v"],
  "v2.7": ["i2v"],
};

// Per-model MAX duration. 15s is exclusive to the v4.0 pair; absent => 10s cap. Enabling V2.7 /
// V3.0 Flash without this would newly expose a 15s option PixAI does not support on those
// engines, at ~84,000 credits for a V2.7 clip with no card to cover it.
export const MODEL_MAXDUR = { "v4.0": 15, "v4.0.1": 15 };

export const MODE_LBL = { i2v: "Start Frame", flf: "Start Frame", r2v: "Image references" };
export const MODE_PH = {
  i2v: "Describe the motion — ‘slow cinematic pan right, gentle waves…’",
  flf: "Describe the transition from start frame to end frame…",
  r2v: "Type @image1 / @video1 / @audio1 to cite a ref — it becomes a chip — ‘the girl from @image1 dances to @audio1…’",
};
export const CHANNEL_CAP = {
  normal: "Please keep creations SFW",
  enhanced: "👑 Enhanced — for professional creators",
};

// Matches the server's VIDEO_DURATIONS / _snap_video_duration -- prefill() snaps to the nearest
// so an out-of-range shot duration (a hand-typed "8") never lands the <select> on a value with
// no matching <option>, which resolves to "" and silently submits duration:0.
export const DURATIONS = [5, 6, 10, 15];
export function snapDuration(d) {
  d = Number(d);
  if (!isFinite(d)) return 5;
  return DURATIONS.reduce((best, v) => (Math.abs(v - d) < Math.abs(best - d) ? v : best));
}

// "a" / "a and b" / "a, b and c" -- the mode-switch hold notice reads like a sentence.
export function joinAnd(parts) {
  if (parts.length < 2) return parts[0] || "";
  return parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1];
}

// A slot item: {media_id, thumb, is_nsfw}. Accepts either media_id or the mid alias, and fills a
// default /thumbs/<id>.jpg when no thumb is given (a prefilled slot may carry a local data-URL).
export function refItem(r) {
  const mid = String(r.media_id || r.mid);
  return { media_id: mid, thumb: r.thumb || ("/thumbs/" + mid + ".jpg"), is_nsfw: !!r.is_nsfw };
}

/* ---- PURE spend-critical state transitions -------------------------------------------------
   These operate on a plain drawer-state object -- {mode, slots, imgSlots, vidSlots, audSlot,
   model, duration, camera, quality, channel, audioGen, audioLanguage, negative, modeNote} -- with
   NO DOM and NO React. They are the SAME functions the <VideoDrawer> component drives AND the loom
   node-tests hit directly (med-mg-generate-drawer-mode-carry, med2-mg-generate-drawer-prefill-leak,
   ...), so the money-bug regressions they pin -- one shot's media reaching another shot's PAID
   payload -- are verified by executing the real transition, not a source-presence proxy. The
   vanilla entangled this logic in <mg-generate-drawer>'s class methods (this._slots + this.
   _renderSlots()); the no-vanilla port (2026-08-08) is where it finally separates from the paint.

   Mode/slot banks: i2v/flf keep their frames in `slots` ([0]=Start, [1]=End for flf); r2v (Multi-
   Reference) keeps picks in the separate imgSlots/vidSlots/audSlot banks. A mode switch NEVER
   writes a priced slot from the r2v banks (that was M27's reverted "carry" -- it put a style-
   reference the user picked into the primary input of a paid render). */

export function primaryBank(s) { return s.mode === "r2v" ? s.imgSlots : s.slots; }
export function setPrimaryBank(s, arr) { if (s.mode === "r2v") s.imgSlots = arr; else s.slots = arr; }

// The notice shown when a USER gesture leaves Multi-Reference for a mode that can't display its
// picks: NAME what is held (nothing is destroyed -- the r2v banks are untouched), never carry it.
export function heldRefsNotice(s, m) {
  const imgs = s.imgSlots.filter((x) => x && x.media_id).length;
  const vids = s.vidSlots.filter((x) => x && x.media_id).length;
  const held = [];
  if (imgs) held.push(imgs + (imgs === 1 ? " image ref" : " image refs"));
  if (vids) held.push(vids + (vids === 1 ? " video ref" : " video refs"));
  if (s.audSlot && s.audSlot.media_id) held.push("the audio ref");
  if (!held.length) return "";
  return "Still held for Multi-Reference: " + joinAnd(held) + ". Nothing was deleted — "
    + (m === "flf" ? "First & Last Frames" : "First Frame") + " has nowhere to show that. Switch "
    + "back to Multi-Reference, on a model that offers it, and it is all still there.";
}

// Slot-bank transition for a mode change. `userDriven` gates ONLY the held-refs notice: a real
// click leaving r2v names what it can't carry; a host re-sync (prefill/gating) stays silent, so a
// sentence about the PREVIOUS shot's refs never sits over the NEW shot's slots. Mutates s.
export function applyMode(s, m, userDriven) {
  const from = s.mode;
  s.mode = m;
  if (m === "i2v") s.slots = [s.slots[0] || null];
  else if (m === "flf") s.slots = [s.slots[0] || null, s.slots[1] || null];
  else if (!s.imgSlots.length) s.imgSlots = [null];
  s.modeNote = (userDriven && from === "r2v" && m !== "r2v") ? heldRefsNotice(s, m) : "";
}

// Shows/hides modes a model doesn't support (MODEL_VMODES) + switches off an invalid one; clamps
// duration to the model's cap. `userDriven` only forwards to applyMode's notice gate.
export function applyModelGating(s, userDriven) {
  const allowed = MODEL_VMODES[s.model] || ["i2v", "flf", "r2v"];
  if (allowed.indexOf(s.mode) === -1) { applyMode(s, allowed[0], userDriven); return; }
  const maxDur = MODEL_MAXDUR[s.model] || 10;
  if (s.duration > maxDur) s.duration = maxDur;
}

// The gallery lightbox / bulk-bar "Send to Video" entry. Image refs only. >1 forces r2v. Writes
// slots[0] and DELIBERATELY leaves flf's End Frame alone (wiping a hand-picked End Frame is data
// loss) -- the whole-bank clear is prefill()'s business, not this. Mutates s.
export function applySetRefs(s, refs) {
  if (!Array.isArray(refs)) return;
  refs = refs.slice(0, 6);
  if (refs.length > 1) applyMode(s, "r2v");
  const slots = refs.map(refItem);
  if (refs.length > 1) setPrimaryBank(s, slots);
  else if (s.mode === "r2v") setPrimaryBank(s, [slots[0] || null]);
  else s.slots[0] = slots[0] || null;
}

// Shot-context prefill: only keys present are applied. Mutates s; returns { setPrompt } -- the
// prompt is a contenteditable side effect the caller applies (this layer stays DOM-free). An
// explicit images array is the COMPLETE list for its shot: the flf branch writes BOTH frame slots
// POSITIONALLY (images[0]->Start, images[1]->End; a null is a positional hole that CLEARS the
// slot), so an unfilled End Frame is nulled rather than inheriting the previous shot's frame (the
// wrong-shot spend bug of 2026-07-27). setRefs cannot do that -- it writes slots[0] only.
export function applyPrefill(s, o) {
  o = o || {};
  s.modeNote = "";
  if (o.mode && MODE_LBL[String(o.mode).toLowerCase()]) applyMode(s, String(o.mode).toLowerCase());
  if (o.video_model != null) s.model = o.video_model;
  if (o.duration != null) s.duration = snapDuration(o.duration);
  if (o.quality != null) s.quality = o.quality;
  if (o.is_private != null) s.channel = o.is_private ? "enhanced" : "normal";
  if (o.audio != null) s.audioGen = !!o.audio;
  if (o.audio_language != null) s.audioLanguage = o.audio_language;
  if (o.negative != null) s.negative = o.negative;
  const imgList = Array.isArray(o.images) ? o.images : (Array.isArray(o.refs) ? o.refs : null);
  if (imgList && s.mode === "flf" && imgList.length <= 2) {
    const flfSlots = imgList.map((r) => (r ? refItem(r) : null));
    s.slots = [flfSlots[0] || null, flfSlots[1] || null];
  } else {
    if (o.refs) applySetRefs(s, o.refs);
    if (o.images) applySetRefs(s, o.images);
  }
  if (Array.isArray(o.video_refs)) s.vidSlots = o.video_refs.slice(0, 3).map(refItem);
  if (o.audio_ref !== undefined) s.audSlot = o.audio_ref ? { media_id: String(o.audio_ref.media_id), filename: o.audio_ref.filename || "audio ref" } : null;
  applyModelGating(s);   // gate LAST, after refs/mode settle
  return { setPrompt: (o.prompt != null) ? o.prompt : null };
}

// The submit/price payload. promptText is passed in (it comes from the contenteditable). Pure.
export function buildPayload(s, promptText) {
  const images = primaryBank(s).filter((x) => x && x.media_id).map((x) => x.media_id);
  const video_refs = s.mode === "r2v" ? s.vidSlots.filter((x) => x && x.media_id).map((x) => x.media_id) : [];
  const audio_refs = (s.mode === "r2v" && s.audSlot && s.audSlot.media_id) ? [s.audSlot.media_id] : [];
  return {
    mode: s.mode.toUpperCase(),
    prompt: promptText || "",
    negative: (s.negative || "").trim(),
    images, video_refs, audio_refs,
    duration: +s.duration,
    audio: s.audioGen,
    video_model: s.model,
    camera_movement: (s.mode !== "r2v" ? s.camera : ""),
    quality: s.quality,
    audio_language: s.audioLanguage,
    is_private: (s.channel === "enhanced"),
  };
}

export function hasAnyRef(p) { return !!(p.images.length || p.video_refs.length || p.audio_refs.length); }
// FLF with an End Frame but NO Start Frame is a DIFFERENT generation -- one predicate for Go AND
// the cost badge (pricing what Go would refuse is the split that let a disabled control charge).
export function flfMissingStart(s) {
  return s.mode === "flf" && !(s.slots[0] && s.slots[0].media_id) && !!(s.slots[1] && s.slots[1].media_id);
}

/* LOCAL PORT of loom/src/loom-mutations.js's friendlyGenErr(raw) -- same regex patterns, same
   replacement text, verbatim -- so a generation rejected by PixAI's content filter (or stopped
   short on insufficient balance) reads IDENTICALLY whether it surfaced via the Loom's own poll
   path or this drawer's independent submit/poll cycle. The mapping is intentionally duplicated
   (there is no shared module the Loom bundle and this can both import at build time without
   pulling in loom-core). A friendly label NEVER replaces the raw text -- it is APPENDED
   (guidance AND ground truth, always). KEEP IN SYNC with loom-mutations.js by hand. */
export function friendlyGenErr(raw) {
  const s = String(raw || "");
  if (!s) return "generation failed";
  let hint = "";
  if (/insufficient|INSUFFICIENT_BALANCE|40300010/i.test(s)) {
    hint = "Out of balance for this model — no free card matched and credits are 0. Claim your daily rewards, or pick a card-covered model.";
  } else if (/maxLength|too long|exceeds maximum/i.test(s)) {
    hint = "That prompt is too long for video — PixAI allows 2000 characters. Trim it and resubmit; nothing was created or charged.";
  } else if (/image contains (sensitive|nsfw|prohibited)|NSFW_DETECTED|40300032/i.test(s)) {
    hint = "PixAI refused the SOURCE IMAGE on content grounds, not the prompt — rewriting the text will not help. Try a different frame.";
  } else if (/moderat|content.?polic|flagged|nsfw/i.test(s)
    || (/prohibit|sensitive|not.?allowed|violat/i.test(s) && /content|prompt|polic|guideline|term|image/i.test(s))) {
    hint = "PixAI's content filter blocked this generation — that's decided on PixAI's side, not here.";
  } else if (/inferenceProfile|i2vPro[./]mode|unknown mode/i.test(s)) {
    hint = "That quality setting isn't available for this model — try a different Mode.";
  }
  return hint ? hint + " (PixAI said: " + s.slice(0, 160) + ")" : s;
}

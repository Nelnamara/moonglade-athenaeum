/* videoDrawerCore.js -- the pure data + helpers of the video Generate drawer, ported VERBATIM
   from static/mg-generate-drawer.js (no-vanilla campaign, component 7 -- the last one). No
   DOM/React dependency, exported individually so the loom node-tests import the real values +
   functions instead of regex-extracting them from a vanilla file. The <VideoDrawer> React
   component consumes all of these. */

// Full site roster, in PixAI's real model-picker order -- newest first, V2.7 last
// (private/VIDEO_MODELS.md, owner screenshots 2026-07-18). All seven are selectable.
// This REAL roster is the data source (drift 22): the DC's demo VIDEO_MODELS (rates, demo caps)
// is the visual spec for the ENGINE card / chips / palette only, never swapped in here. The
// '~2.5× cost' chip on V4.0 Preview is not in the DC's caps (fidelity checklist, EXTRA) -- kept:
// it is the roster's own cost caution for the dearest engine, and the roster is the source.
export const MODELS = [
  { value: "v4.0", label: "V4.0 Preview", caps: ["multi-ref", "audio", "15s", "top quality", "~2.5× cost"] },
  { value: "v4.0.1", label: "V4.0 Lite Preview", caps: ["multi-ref", "audio", "15s", "end-frame"] },
  { value: "v3.2", label: "V3.2", caps: ["audio", "prompt-following"] },
  { value: "v3.0.2", label: "V3.0 Lite", caps: ["complex motion", "cheap"] },
  { value: "v3.0", label: "V3.0 (High Consistency)", caps: ["high-consistency", "action presets", "start/end"] },
  { value: "v3.0.1", label: "V3.0 Flash", caps: ["multi-shot", "hires", "fastest", "no card"] },
  { value: "v2.7", label: "V2.7 (High Dynamics)", caps: ["camera moves", "dynamic", "no card"] },
];
// The engine the drawer opens on. The DC marks it with an emerald 'default' chip (DC 1846 V4.0
// Lite caps end with ['default','hot']); modelCaps() appends that chip to THIS engine's real caps.
export const DEFAULT_MODEL = "v4.0.1";
// Free-card eligibility per engine (real roster: the two 'no card' engines). Absent => cards
// apply. Static capability knowledge for the ENGINE card's meta line (DC 2900 videoModelMeta) --
// the PRICE, and whether a card actually covers THIS clip, stays CostBadge's truth.
export const MODEL_CARD = { "v3.0.1": false, "v2.7": false };
// The DC's capStyle kind tiers (DC 1877-1880): 'hot' = emerald, 'crown' = pink, else plain.
// Mapped by cap TEXT so the real caps above stay plain strings.
export const CAP_KIND = { "top quality": "crown", "cheap": "hot", "fastest": "hot", "default": "hot" };
// [label, kind] pairs for the chip row: the engine's real caps, plus 'default' on DEFAULT_MODEL.
export function modelCaps(v) {
  const m = MODELS.find((x) => x.value === v);
  const caps = (m ? m.caps : []).map((c) => [c, CAP_KIND[c] || ""]);
  if (v === DEFAULT_MODEL) caps.push(["default", "hot"]);
  return caps;
}
// DC 2900: videoModelMeta = maxDur + 's max · ' + (card ? 'V4.0 cards apply' : 'never card-covered').
export function modelMeta(v) {
  return (MODEL_MAXDUR[v] || 10) + "s max · " + (MODEL_CARD[v] === false ? "never card-covered" : "V4.0 cards apply");
}
export const SHOT_LABEL = { i2v: "First Frame", flf: "First & Last", r2v: "Multi-Reference" };

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

// The primary bank's label per mode (DC 2851/2858 bank.label; casing is the DC's).
export const MODE_LBL = { i2v: "Start frame", flf: "Start frame", r2v: "Image references" };
export const MODE_PH = {
  i2v: "Describe the motion — ‘slow cinematic pan right, gentle waves…’",
  flf: "Describe the transition from start frame to end frame…",
  r2v: "Type @image1 / @video1 / @audio1 to cite a ref — it becomes a chip — ‘the girl from @image1 dances to @audio1…’",
};
export const CHANNEL_CAP = {
  normal: "Please keep creations SFW",
  enhanced: "👑 Enhanced — for professional creators",
};
// The CAMERA <select>'s options, value + label, in the DC's exact order (DC 1405-1411). The
// values are PixAI's i2vPro.cameraMovement keys (unchanged); the labels are the DC's.
export const CAMERA_OPTS = [
  ["unset", "Unset"], ["horizontal", "Horizontal"], ["pan", "Pan"], ["roll", "Roll"],
  ["tilt", "Tilt"], ["vertical-pan", "Vertical pan"], ["zoom", "Zoom"],
];
// The audio-language <select>'s options (DC 1435-1438 draws the first four). 'none' = SE only
// is a REAL PixAI value (moonglade_backup.VIDEO_AUDIO_LANGS), so it stays -- real capability
// over the DC's demo list, the same call as the engine roster; owner to rule if it should go.
export const AUDIO_LANGS = [
  ["english", "English"], ["japanese", "Japanese"], ["chinese", "Chinese"], ["korean", "Korean"],
  ["none", "SE only (no dialogue)"],
];

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
   model, duration, camera, quality, channel, audioGen, audioLanguage, videoHelper, negative,
   modeNote} -- with
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

// The DC's Multi-Reference bank shape (DC 2847-2856): the FILLED slots plus ONE trailing empty
// '+ image' / '+ video' slot auto-appended while under the cap -- no separate add control, and
// never two empty slots at once. The backing arrays may still carry an explicit null (the [null]
// seed applyMode/prefill leave), so this maps the paint back onto real indices: `filled` are the
// picks with the index a remove/re-pick must address; `nextIndex` is where the trailing slot's
// pick lands (the first hole, else the end), or -1 at the cap.
export function bankView(arr, max) {
  const filled = [];
  let hole = -1;
  (arr || []).forEach((item, index) => {
    if (item && item.media_id) filled.push({ item, index });
    else if (hole < 0) hole = index;
  });
  const nextIndex = filled.length >= max ? -1 : (hole >= 0 ? hole : (arr || []).length);
  return { filled, nextIndex };
}

// What the Multi-Reference banks are holding, as the DC phrases it (DC 2222-2226): comma-joined
// '<n> image ref(s)', '<n> video ref(s)'. The audio ref rides along when one is held -- the DC has
// no audio bank to name, but this drawer does (owner-locked PixAI parity), and a notice that
// stays silent about a held audio ref is the M27 shape again.
export function heldList(s) {
  const imgs = s.imgSlots.filter((x) => x && x.media_id).length;
  const vids = s.vidSlots.filter((x) => x && x.media_id).length;
  const held = [];
  if (imgs) held.push(imgs + (imgs === 1 ? " image ref" : " image refs"));
  if (vids) held.push(vids + (vids === 1 ? " video ref" : " video refs"));
  if (s.audSlot && s.audSlot.media_id) held.push("the audio ref");
  return held;
}

// The notice shown when a USER gesture leaves Multi-Reference for a mode that can't display its
// picks: NAME what is held (nothing is destroyed -- the r2v banks are untouched), never carry it.
// Copy is the DC's pickShot heldNote verbatim (DC 2225-2227). `_m` (the target mode) is kept for
// the call signature; the DC copy does not name it.
export function heldRefsNotice(s, _m) {
  const held = heldList(s);
  if (!held.length) return "";
  return "Still held for Multi-Reference: " + held.join(", ") + ". Nothing was deleted.";
}

// Slot-bank transition for a mode change. `userDriven` gates ONLY the held-refs notice: a real
// click leaving r2v names what it can't carry; a host re-sync (prefill/gating) stays silent, so a
// sentence about the PREVIOUS shot's refs never sits over the NEW shot's slots. Mutates s.
export function applyMode(s, m, userDriven) {
  const from = s.mode;
  s.mode = m;
  if (m === "i2v") s.slots = [s.slots[0] || null];
  else if (m === "flf") s.slots = [s.slots[0] || null, s.slots[1] || null];
  else {
    // r2v: ensure each bank carries at least its one empty slot, matching the vanilla's
    // _renderSlots/_renderVidSlots normalization. Without normalizing vidSlots here the render's
    // `vidSlots.length ? vidSlots : [null]` fallback fabricates a slot the backing array doesn't
    // have, so a first "+ add" click just re-derives the same single slot (a no-op).
    if (!s.imgSlots.length) s.imgSlots = [null];
    if (!s.vidSlots.length) s.vidSlots = [null];
  }
  s.modeNote = (userDriven && from === "r2v" && m !== "r2v") ? heldRefsNotice(s, m) : "";
}

// Dims modes a model doesn't support (MODEL_VMODES) + switches off an invalid one; clamps
// duration to the model's cap. `userDriven` gates the notice: a real engine pick that drops the
// shot mode explains itself in the DC's pickVideoModel words (DC 2232-2246) -- '<engine> has no
// <dropped mode>, so the shot mode switched to <new mode>.' + what the r2v banks still hold; a
// host re-sync (prefill) stays silent. The target is the LAST supported mode, as the DC picks
// it (V3.2 from Multi-Reference lands on First & Last, not First Frame). Spend-safe either way:
// applyMode only ever re-shapes the i2v/flf `slots` bank the user filled; the r2v banks are
// never carried into it.
export function applyModelGating(s, userDriven) {
  const allowed = MODEL_VMODES[s.model] || ["i2v", "flf", "r2v"];
  if (allowed.indexOf(s.mode) === -1) {
    const from = s.mode, to = allowed[allowed.length - 1];
    applyMode(s, to, userDriven);
    if (userDriven) {
      const m = MODELS.find((x) => x.value === s.model);
      const held = heldList(s);
      s.modeNote = (m ? m.label : s.model) + " has no " + (SHOT_LABEL[from] || from) + ", so the shot mode switched to "
        + SHOT_LABEL[to] + "." + (held.length ? " Still held: " + held.join(", ") + ". Nothing was deleted." : "");
    }
  }
  // Clamp duration to the model's cap UNCONDITIONALLY -- the vanilla _applyModelGating fell
  // through to this after the mode switch. An earlier `return` right after applyMode() skipped it,
  // so switching from a V4.0/15s state to a 10s-cap engine (its mode ALSO unsupported, e.g.
  // r2v->i2v) left duration:15 in the priced + submitted payload. That is a real spend-path
  // divergence (the MODEL_MAXDUR comment cites ~84,000 credits for a V2.7 15s clip).
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
  if (o.prompt_helper != null) s.videoHelper = !!o.prompt_helper;
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
    // The DC's 'Video prompt helper' switch (DC 2921, off by default -- the opposite of image
    // gen). Rides the payload -> i2vPro.usePromptsHelper on the server (I2V/FLF only; the
    // verified referenceVideo shape has no such field), and so lives in priceKey like every
    // other submitted field.
    prompt_helper: !!s.videoHelper,
  };
}

export function hasAnyRef(p) { return !!(p.images.length || p.video_refs.length || p.audio_refs.length); }

/* ---- price identity: the settled quote must be FOR the payload Go would submit ------------
   State alone cannot gate a spend: the badge can hold a settled FREE for a 5s payload while
   the form already says 15s (a 250ms debounce + one RTT of stale FREE), or hold a price for a
   payload whose quality/camera has since changed with NO re-price pending at all. So the host
   records the priceKey of the payload it actually priced, and Go compares it against the
   priceKey of the payload it is about to submit -- identity, not timing.

   priceKey drops ONLY prompt/negative. Everything else rides the priced request (the whole
   i2vPro/referenceVideo block is a _PRICE_NESTED field of moonglade_backup.price_task, and
   modelId a _PRICE_SCALARS one), so a field that does not really move the price (channel,
   camera) still lives in the key: the cost of over-including is a re-price the change handler
   already schedules; the cost of under-including is a spend against the wrong quote. Prompt
   text is excluded because it is the one field the drawer edits without a repaint (imperative
   contenteditable) and it never prices -- see loom-core.js's PRICE_FIELDS for the same call. */
export const PRICE_KEY_SKIP = ["prompt", "negative"];
export function priceKey(payload) {
  if (!payload || typeof payload !== "object") return "";
  const keys = Object.keys(payload).filter((k) => PRICE_KEY_SKIP.indexOf(k) === -1).sort();
  return JSON.stringify(keys.map((k) => [k, payload[k]]));
}
// The Go gate. `price` = {settled, pricedKey, pendingTimer}: settled = the badge shows the
// verdict for pricedKey; pendingTimer = a re-price is scheduled but has not fired (so whatever
// is on the badge is already known-stale). True only when a settled verdict exists AND nothing
// is pending AND that verdict was priced off THIS payload.
export function canSubmit(price, payload) {
  return !!(price && price.settled && !price.pendingTimer && price.pricedKey != null
    && price.pricedKey === priceKey(payload));
}
// How long the drawer waits on /api/price before aborting into the "couldn't verify" verdict.
// Go is gated on the fetch settling, so an UNBOUNDED fetch that hangs (browser<->server stall)
// would leave Go disabled forever with no message. The server's own upstream PixAI calls are
// bounded at 30s/60s, so 25s here only ever fires on a transport stall, not a slow price.
export const PRICE_FETCH_TIMEOUT_MS = 25000;
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

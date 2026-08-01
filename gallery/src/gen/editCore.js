/* Edit + Fix logic, ported verbatim-in-behavior from the classic Gen IIFE
   (moonglade_gallery.py ~8590-8825) against the 2026-07-29 recon map.

   EDIT_CAPS mirrors core.EDIT_MODELS's caps (capability probe 2026-07-06). The
   client sends the string KEY (`edit_model`), never a model id -- the server
   resolves it via core.edit_model_id(). */

export const EDIT_CAPS = {
  "edit-pro": {
    label: "Edit Pro", max_refs: 4,
    resolutions: ["1K", "2K"],
    qualities: ["low", "medium", "high"],
    aspects: ["16:9", "9:16", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "1:3", "3:1"],
    def: { resolution: "1K", quality: "medium", aspect: "3:4" },
  },
  "reference-pro": {
    label: "Reference Pro", max_refs: 10,
    resolutions: ["2K", "4K"],
    qualities: [],
    aspects: ["16:9", "9:16", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "21:9"],
    def: { resolution: "2K", quality: "", aspect: "3:4" },
  },
};
export const DEFAULT_EDIT_MODEL = "edit-pro";

// Fix: face/hand box colors and the classic's minimum drag size (DISPLAY px).
export const FIX_COLORS = { face: "#b692e6", hand: "#4fc99a" };
export const FIX_MIN_PX = 6;
export const FIX_MAX_BOXES = 20;   // clean_fix_boxes truncates at 20 server-side

export const editCaps = (model) => EDIT_CAPS[model] || EDIT_CAPS[DEFAULT_EDIT_MODEL];

/* @image1 is ALWAYS the primary source; extras number from @image2 by position
   (the classic's hard-coded +2 offset over editRefs). */
export const refTag = (i) => "@image" + (i + 2);

/* editPayload -- the SAME object goes to /api/price and /api/edit, so a quote
   can never describe a different edit than the submit. `no_card` is never sent. */
export function buildEditPayload(s) {
  const prim = (s.source || "").trim();
  return {
    mode: "edit",
    edit_model: s.model,
    source: prim,
    sources: [prim].concat(s.refs.map((r) => r.media_id)).filter(Boolean),
    instruction: (s.instruction || "").trim(),
    preset: s.preset || "",
    resolution: s.resolution,
    quality: s.quality || "",
    aspect: s.aspect,
  };
}

/* The server needs a source AND (a preset OR an instruction) -- its two 400s. */
export function editGate(s) {
  if (!(s.source || "").trim()) return "Pick an image to edit";
  if (!s.preset && !(s.instruction || "").trim()) return "Describe the edit (or pick a preset)";
  return null;
}

/* Boxes live in state as {x,y,w,h,tag} in DISPLAY pixels; the wire wants
   {x,y,width,height,tag} in ORIGINAL-image pixels. The scale comes from the
   rendered <img> -- naturalWidth/clientWidth -- and the server does NOT rescale,
   so getting this wrong repairs the wrong part of the picture. */
export function scaleBoxes(boxes, imgEl) {
  const scale = imgEl && imgEl.clientWidth
    ? (imgEl.naturalWidth / imgEl.clientWidth) : 1;
  return boxes.map((b) => ({
    x: Math.round(b.x * scale),
    y: Math.round(b.y * scale),
    width: Math.round(b.w * scale),
    height: Math.round(b.h * scale),
    tag: b.tag,
  }));
}

export const EDIT_DEFAULTS = {
  model: DEFAULT_EDIT_MODEL,
  source: "", refs: [],
  instruction: "", preset: "",
  resolution: EDIT_CAPS[DEFAULT_EDIT_MODEL].def.resolution,
  quality: EDIT_CAPS[DEFAULT_EDIT_MODEL].def.quality,
  aspect: EDIT_CAPS[DEFAULT_EDIT_MODEL].def.aspect,
};

/* Switching model re-defaults res/quality/aspect and TRIMS refs over the new
   cap, with the classic's own wording (the count includes the primary). */
export function switchEditModel(s, next) {
  const caps = editCaps(next);
  const maxAdd = Math.max(0, caps.max_refs - ((s.source || "").trim() ? 1 : 0));
  let refs = s.refs, notice = null;
  if (refs.length > maxAdd) {
    const had = refs.length, dropped = had - maxAdd;
    refs = refs.slice(0, maxAdd);
    notice = {
      title: "Only " + maxAdd + " reference image" + (maxAdd === 1 ? "" : "s") + " kept",
      msg: caps.label + " takes up to " + caps.max_refs +
           " images in total (the one being edited counts as one) — " +
           dropped + " of your " + had + " references were left out.",
    };
  }
  return {
    next: {
      ...s, model: next, refs,
      resolution: caps.def.resolution,
      quality: caps.def.quality,
      aspect: caps.def.aspect,
    },
    notice,
  };
}

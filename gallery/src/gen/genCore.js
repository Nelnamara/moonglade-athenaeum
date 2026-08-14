/* Pure logic for the pilot's Generate (image) surface. Ported from the classic
   Gen IIFE against the recon maps of 2026-07-29, then corrected against a
   three-lens adversarial review the same night -- the review's parity findings
   are cited inline where they changed a line.

   SPEND-SAFETY CONTRACT (from the server's own guards -- do not weaken):
   - NEVER auto-retry a POST to a spend route. gql_mutate's no-retry covers the
     server->PixAI hop only; a client re-POST creates a second charged task.
   - Errors come back HTTP 200 {"error": ...}. Key off the body (d.error ||
     !d.task_id), never off r.ok.
   - ALWAYS send model_id with version_id (a bare version_id bypasses the
     server's version re-validation).
   - Surface `adjusted` UNCONDITIONALLY -- clamps are substitutions on a PAID
     path, and a toast that needs window.Toast is not a receipt.
   - Never set no_card: free-card auto-apply is the server's job and opting out
     silently burns credits.
   - A failed price check is "could not verify", NEVER "free" and never blank. */

// PixAI's own captured Enhance Details values (task 2039053268124647852,
// 2026-07-28) -- same constants the classic chip carries.
export const MG_HIRES = { ratio: 1.5, denoise: 0.6 };

// The classic's own sets (review: the first cut shrank both and moved the
// default). Aspect default 1:1, sizes through 2048.
export const ASPECTS = [
  ["1:1", 1], ["3:4", 3 / 4], ["4:3", 4 / 3], ["2:3", 2 / 3],
  ["3:2", 3 / 2], ["9:16", 9 / 16], ["16:9", 16 / 9], ["3:1", 3],
];
export const SIZES = [768, 1024, 1536, 2048];
export const MODES = [
  ["auto", "Auto"], ["lite", "Lite"], ["standard", "Standard"],
  ["pro", "Pro"], ["ultra", "Ultra"],
];

// The classic's blank-steps fallback: `+el('gen-steps').value||25`.
export const STEPS_FALLBACK = 25;

const d8 = (n) => Math.max(64, Math.min(4096, Math.round(n / 8) * 8));

/* Resolution: custom W×H (both set) wins; else aspect scaled so the LONG edge is
   the size select; /8 snapped, 64..4096 -- the classic dims() contract. */
export function dims(s) {
  const cw = parseInt(s.customW, 10), ch = parseInt(s.customH, 10);
  if (cw > 0 && ch > 0) return { width: d8(cw), height: d8(ch) };
  const r = s.aspect || 1;
  const size = s.size || 1024;
  return r >= 1
    ? { width: d8(size), height: d8(size / r) }
    : { width: d8(size * r), height: d8(size) };
}

/* LoRA weight bounds come from the SELECTED BASE model's architecture, not the
   LoRA's own (review: the first cut keyed them to lora_base_type, which handed
   an unresolved LoRA the widest range). Keys are uppercased like the classic. */
export function loraRange(baseModelType) {
  const t = (typeof window !== "undefined" && window.MG_LORA) || {};
  const key = String(baseModelType || "").toUpperCase();
  return (t.ranges && t.ranges[key]) || t.fallback || [-2, 2];
}
export function loraStep() {
  const t = (typeof window !== "undefined" && window.MG_LORA) || {};
  return t.step || 0.05;
}

/* The classic's reclampLoras: switching base model/version re-clamps every
   attached weight into the new architecture's range. Without it an SDXL weight
   of -0.8 rides a DiT submit that only accepts 0..1.2 -- on a paid path. */
export function clampLoras(loras, baseModelType) {
  const [lo, hi] = loraRange(baseModelType);
  return loras.map((l) => {
    const w = Math.max(lo, Math.min(hi, Number(l.weight)));
    return w === Number(l.weight) ? l : { ...l, weight: w };
  });
}

/* Architecture mismatch: EXACT equality when both sides are known (uppercased),
   unknown on either side fails open -- the classic's contract. */
export function loraIncompat(lora, model) {
  if (!model || !model.model_type || !lora.lora_base_type) return false;
  return String(lora.lora_base_type).toUpperCase() !== String(model.model_type).toUpperCase();
}

/* The Go gate, classic chain: resolved version + prompt + no unresolved/failed
   LoRA + no architecture mismatch + count within the account cap. */
export function goGate(s, loraCap) {
  if (!s.model || !s.model.version_id) return "Pick a model first";
  if (!s.prompt.trim()) return "Write a prompt";
  if (s.loras.some((l) => l.failed)) return "A LoRA failed to resolve — remove it";
  if (s.loras.some((l) => !l.version_id)) return "A LoRA is still resolving";
  if (s.loras.some((l) => loraIncompat(l, s.model))) return "A LoRA does not match this model's architecture";
  if (loraCap != null && s.loras.length > loraCap) return "Over your LoRA cap (" + loraCap + ")";
  return null;
}

/* THE payload builder -- one function feeds BOTH /api/price and /api/generate,
   the invariant the classic keeps (the quote and the spend cannot diverge). */
export function buildPayload(s) {
  const { width, height } = dims(s);
  const hires = s.boosters.hires && !(s.model && s.model.compat_upscale === false);
  // One effective steps value for BOTH steps and the mirrored denoise steps --
  // the classic sends its ||25 fallback to both (review: sending null to one and
  // a number to the other made the upscale pass stop mirroring sampling steps).
  const eff = s.steps === "" ? STEPS_FALLBACK : Number(s.steps);
  return {
    version_id: s.model ? s.model.version_id : "",
    model_id: s.model ? s.model.model_id : "",
    prompt: s.prompt,
    negative: s.negative,
    width, height,
    mode: s.mode || "auto",
    steps: eff,
    cfg: s.cfg === "" ? null : Number(s.cfg),
    count: Math.max(1, Math.min(4, Number(s.count) || 1)),
    seed: s.seed === "" ? null : s.seed,
    high_priority: !!s.highPriority,
    prompt_helper: !!s.promptHelper,
    ref_media_id: s.ref ? s.ref.media_id : null,
    ref_strength: s.ref ? Number(s.refStrength) : null,
    upscale: hires ? MG_HIRES.ratio : null,
    upscale_denoise: hires ? MG_HIRES.denoise : null,
    upscale_denoise_steps: hires ? eff : null,
    face_fix: !!s.boosters.face,
    quality_tag: s.boosters.quality ? "Masterpiece" : null,
    loras: s.loras.filter((l) => l.version_id)
      .map((l) => ({ version_id: l.version_id, weight: Number(l.weight) })),
  };
}

/* The classic's curated error guidance (moonglade_gallery.py friendlyGenErr).
   This is the THIRD hand-maintained copy -- the others live in
   gallery/src/gen/videoDrawerCore.js (the video drawer's copy) and
   loom/src/loom-mutations.js. Keep the wording in step with them;
   loom/test/mg-generate-drawer-parity.test.js watches the videoDrawerCore copy. */
/* Remix (issue #4): turn /api/task-params' successful answer into the rows the
   composer may ADD and the disclosures the reuse chip must carry. Pure --
   pinned by loom/test/mg-remix-lora-plan.test.js. The composer keys LoRAs by
   model_id, so a second version of the same LoRA model cannot ride; it is
   COUNTED into the disclosed note, never silently merged or retuned with the
   first version's weight (adversarial review 2026-08-13, finding 1.1). Rows
   with missing ids are counted the same way -- an uncounted skip is a silent
   substitution on a paid path. `hadLoras` is the catalog's own "this task used
   LoRAs" signal: a clean-empty answer against a non-empty catalog string is a
   failed restore, not a LoRA-free recipe. */
export function planLoraRestore(dt, hadLoras) {
  const rows = [], notes = [];
  let missed = Number(dt && dt.unresolved) || 0, degraded = 0;
  const seen = new Set();
  for (const lr of ((dt && dt.loras) || [])) {
    if (!lr.model_id || !lr.version_id) { missed += 1; continue; }
    if (seen.has(lr.model_id)) { missed += 1; continue; }
    seen.add(lr.model_id);
    if (lr.degraded) degraded += 1;
    rows.push(lr);
  }
  if (!rows.length && !missed && hadLoras) notes.push("LoRAs could not be restored");
  if (missed) notes.push(missed + (missed > 1 ? " LoRAs" : " LoRA") + " could not be restored");
  if (degraded) notes.push("a LoRA's compatibility data is unverified");
  return { rows, notes };
}

export function friendlyGenErr(raw) {
  const e = String(raw || "");
  const add = (hint) => e + " — " + hint;
  if (/insufficient|40300010|balance/i.test(e))
    return add("your credit balance can't cover this one. Claim your daily credits or lower the size/count.");
  if (/maxLength|too long/i.test(e))
    return add("the prompt is over PixAI's length limit — trim it and try again.");
  if (/NSFW_DETECTED|40300032/i.test(e))
    return add("PixAI's moderation flagged the source image, not your prompt.");
  if (/moderation|blocked|violat/i.test(e))
    return add("PixAI's moderation rejected this one.");
  if (/inferenceProfile|quality mode|profile/i.test(e))
    return add("that quality mode isn't available for this model — try Auto.");
  if (/LORA_NUM_EXCEEDED|40300027/i.test(e))
    return add("too many LoRAs for your membership tier.");
  return e;
}

export const GEN_DEFAULTS = {
  model: null,          // {model_id, title, version_id, model_type, versions[],
                        //  preset:{...}, caps[], compat_*, restrictions}
  loras: [],            // {model_id, title, preview_url, version_id, weight,
                        //  lora_base_type, trigger_words:STRING, versions[], failed}
  prompt: "", negative: "",
  aspect: 1, size: 1024, customW: "", customH: "",
  steps: "", cfg: "", seed: "", count: 1,
  mode: "auto", highPriority: false, promptHelper: true,  // classic defaults
  ref: null, refStrength: 0.55,
  boosters: { hires: false, quality: false, face: false },
};

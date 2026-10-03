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

import {
  accountSizeRule, autoActive, autoDims, contextMax, contextModel, creativityModel, deadRefs,
  effectiveCreativity, effectiveTier, onContextSide, profileLocked, profileRows, ratioIndexOf,
  sizeTiers, tierDims,
} from "./tsubakiCore.js";
import { paletteForPayload } from "./colorPaletteCore.js";
import { recipeGate } from "../recipes/recipesCore.js";

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

/* Does this model offer that mode? (SCOPE 2026-08-17 §4b, capture 2026-08-25.)

   The five bars above are a FIXED list; the real allowed set is per model VERSION and
   comes back from the server as `model.profiles` (a list of profileName strings) --
   Tsubaki.2 offers lite/standard/pro/ultra, Tsubaki.3 offers only pro/ultra. Before this,
   every bar was always clickable, so you could pick a mode the model rejects; the submit
   then dropped the profile and re-ran on the model's own default, which is not the tier
   the cost badge quoted (the divergence genCore's own rule at "quote == spend" forbids).

   FAILS OPEN, deliberately, on every uncertain input:
   - `auto` is ALWAYS offered -- it is our word for "let the server choose", not a
     profileName, so no model can fail to have it.
   - profiles null/undefined (server could not determine them) -> everything offered.
   - profiles [] (an SDXL model: definitively no inference profiles) -> everything
     offered; that architecture is handled by the submit/price gate, not by this bar.
   A `membershipOnly` profile IS in the list and so stays offered -- the site's own
   rejection path owns membership, and a second copy of that rule here would drift. */
export function modeOffered(mode, profiles) {
  if (mode === "auto") return true;
  if (!Array.isArray(profiles) || profiles.length === 0) return true;
  return profiles.some((p) => String(p).toLowerCase() === String(mode).toLowerCase());
}

/* The mode that SURVIVES applying a model version (red team 2026-09-07, refining the
   2026-08-17 §4b ruling above rather than reversing it).

   Dimming a bar only governs the NEXT click. A mode picked on one model stayed selected
   when you switched to a model whose profiles omit it: the bar dimmed but still painted
   filled, buildPayload still sent that mode, /api/price still quoted that tier, and the
   submit was then rejected and silently re-run on the model's own default -- the exact
   quote-vs-charge divergence the dimming exists to close, reached by a model switch
   instead of a click. So the mode is re-checked at the moment a version applies and drops
   back to `auto` when the newly applied version does not offer it.

   `auto` is the only safe landing: it is always offered (see modeOffered) and it is what
   GEN_DEFAULTS starts on, so this can only ever move a selection to the state a fresh
   session is already in -- never onto another priced tier the user did not choose. Fails
   open exactly as modeOffered does: an unknown/empty profile set keeps the mode untouched. */
export function modeAfterApply(mode, profiles) {
  return modeOffered(mode, profiles) ? mode : "auto";
}

// The classic's blank-steps fallback: `+el('gen-steps').value||25`.
export const STEPS_FALLBACK = 25;

const d8 = (n) => Math.max(64, Math.min(4096, Math.round(n / 8) * 8));

/* The model's size rule (SCOPE_2026-09-26 G1). `rule` is /api/model-version's size_rule
   {step, lo, hi} -- the SAME rule the server's gate snaps to (moonglade_backup._snap_size),
   in the same arithmetic, so the drawer's "→ W × H px" line is the size that is sent.
   It is the APP'S OWN rule, not PixAI's: a size already on the step and inside [lo, hi]
   passes untouched (2048×1152, 816×2448, 1088×1824 never move); a failing one is scaled
   proportionally -- long side down to hi if over, then short side up to lo if under, the
   long side winning -- each side rounded half-up to the step, then clamped into [lo, hi].
   No rule (unknown architecture) -> the size as given. Pinned against the Python by
   tests/test_tsubaki3_image_gate.py (all 32 aspect × size presets). */
export function snapSize(w, h, rule) {
  if (!rule || !(Number(rule.step) > 0)) return { width: w, height: h };
  const step = Number(rule.step), lo = Number(rule.lo), hi = Number(rule.hi);
  if (w % step === 0 && h % step === 0 && w >= lo && w <= hi && h >= lo && h <= hi) {
    return { width: w, height: h };
  }
  const longSide = Math.max(w, h), shortSide = Math.min(w, h);
  let s = 1.0;
  if (longSide > hi) s = hi / longSide;
  if (shortSide > 0 && shortSide * s < lo) s = lo / shortSide;
  if (longSide * s > hi) s = hi / longSide;
  const r = (x) => Math.floor(x / step + 0.5) * step;
  return {
    width: Math.min(hi, Math.max(lo, r(w * s))),
    height: Math.min(hi, Math.max(lo, r(h * s))),
  };
}

/* Resolution: custom W×H (both set) wins; else aspect scaled so the LONG edge is
   the size select; /8 snapped, 64..4096 -- the classic dims() contract -- and then onto
   the picked model's size rule when it has one (see snapSize). */
export function dims(s) {
  const info = sizeInfo(s);
  return { width: info.width, height: info.height };
}

/* Is the frame landscape? The aspect decides when it is not square; a square frame keeps the
   Portrait | Landscape switch's own state (decision 7: the switch flips every ratio, 1:1 too). */
export function landscapeOf(s) {
  const a = Number(s && s.aspect) || 1;
  if (a > 1.0001) return true;
  if (a < 0.9999) return false;
  return !!(s && s.landscape);
}

/* dims() with its provenance, for the size line (decisions 6 + 7): what is sent and why.
   source: "custom" (W × H typed, clamped to the account's limit on a tiered model), "auto"
   (Context side, from @image1), "tier" (the ratio on the tier in force), "long" (a model
   without tiers: the long-edge stops). `held` = decision 7's "short edge held at 512". */
export function sizeInfo(s) {
  const m = s.model;
  const tiers = sizeTiers(m);
  const cw = parseInt(s.customW, 10), ch = parseInt(s.customH, 10);
  if (cw > 0 && ch > 0) {
    const d = snapSize(d8(cw), d8(ch), tiers ? accountSizeRule(m, s.member) : (m && m.size_rule));
    return { ...d, source: "custom", tier: null, held: false };
  }
  if (tiers) {
    const tier = effectiveTier(m, s.tier, s.member);
    if (autoActive(s)) {
      const a = autoDims(m, tier, (s.ctx || [])[0]);
      if (a) return { ...snapSize(a.width, a.height, m.size_rule), source: "auto", tier, held: a.held };
    }
    const i = Math.max(0, ratioIndexOf(s.aspect));
    const t = tierDims(m, tier, i, landscapeOf(s));
    return { ...snapSize(t.width, t.height, m.size_rule), source: "tier", tier, held: t.held };
  }
  return { ...legacyDims(s), source: "long", tier: null, held: false };
}

function legacyDims(s) {
  const rule = s.model && s.model.size_rule;
  const r = s.aspect || 1;
  const size = s.size || 1024;
  return r >= 1
    ? snapSize(d8(size), d8(size / r), rule)
    : snapSize(d8(size * r), d8(size), rule);
}

/* A reference on this model goes out as a CONTEXT IMAGE, not img2img (SCOPE_2026-09-26 G3):
   /api/model-version says context_images === true only when PixAI's /features answered
   modelType MMDIT26B_MODEL with contextImages on -- the exact condition the server's gate
   converts on. A context image carries no strength and no negative prompt, so the STRENGTH
   slider and the negative box read disabled while one is set, and the negative is not sent. */
export function refIsContext(s) {
  return !!(s && s.ref && s.model && s.model.context_images === true);
}

/* Session H decision 1: on a context-image model the LoRAs | Context images switch REPLACES the
   single reference slot, so a reference left in the state from another model is neither shown
   nor sent there (it would otherwise ride the gate into a context image nobody can see). */
export function refSent(s) {
  return !!(s && s.ref && !contextModel(s.model));
}

/* The Quality Tag chip's tooltip, read from the picked version's own tag (G4). */
export function qualityTagTitle(m) {
  if (m && m.compat_quality === false) return "This model version publishes no quality tag";
  const q = m && m.quality_tag;
  if (q && (q.prefix || q.suffix)) {
    const bits = [];
    if (q.prefix) bits.push("before: " + q.prefix);
    if (q.suffix) bits.push("after: " + q.suffix);
    return "Adds this model's own quality tag (" + bits.join(" · ") + ")";
  }
  return "Adds PixAI's quality tag to the prompt";
}

/* The server names a receipt's field by PixAI's parameter; the owner reads the drawer's own
   word for it (owner walk 2026-09-29: the note read "promptHelper medium→low" where the dock
   says "creativity"). A field not listed here is already a plain word (width, steps, …). */
const ADJUSTED_WORDS = {
  promptHelper: "creativity", negativePrompts: "negative prompt", colorPalette: "palette",
  enableADetailer: "Face Fix", qualityTag: "Quality Tag", cameraMovement: "camera movement",
  inputVideoDurations: "clip lengths",
};

/* One line of text for a server receipt (`adjusted`: [{field, asked, used, why}]). `used`
   null means the field is not sent -- read "off". A long value (a negative prompt the
   model does not take) is shortened. Shared by the submit result line (submitTask.js) and
   the cost badge's note line, so the two say the same thing. */
export function adjustedText(list) {
  const short = (v) => {
    const t = v == null ? "off" : String(v);
    return t.length > 24 ? t.slice(0, 23) + "…" : t;
  };
  const word = (f) => (Object.prototype.hasOwnProperty.call(ADJUSTED_WORDS, f) ? ADJUSTED_WORDS[f] : f);
  return (Array.isArray(list) ? list : [])
    .map((a) => word(a && a.field) + " " + short(a && a.asked) + " → " + short(a && a.used))
    .join(", ");
}

/* ---- Tsubaki.3 Unlimited Mode (SCOPE_2026-09-26_unlimited-mode, §8 amendments binding) ----
   The server owns the lane: it reads the entitlement live, checks every rule on the gated
   request and refuses what breaks one (moonglade_backup._unlimited_check). The drawer's half
   is the switch, the locks and the reasons, read off the applied version's `unlimited` meta:
   {owned, expires_at, days_left, size: {max_area, max_side, ranges} | null}. */

export const UNLIMITED_BUSY = "An Unlimited Mode picture is still being made";
export const UNLIMITED_PRO = "Unlimited Mode runs on Pro";

/* Offered only when the applied version's status says owned (never assumed). */
export function unlimitedOffered(m) {
  return !!(m && m.unlimited && m.unlimited.owned === true);
}

/* The lane's size limit for this model, or null when the server sent none. */
function laneSize(m) {
  const u = m && m.unlimited;
  return u && u.size && Number(u.size.max_area) > 0 ? u.size : null;
}

/* The site's own size rule on the size actually sent (dims() is already snapped onto the
   model's grid): the area fits the smallest range's max area and the size lies inside a
   range (§8.5 -- 1800×1800 snaps to 1808×1808 and fails). No limit known -> true; the server
   still refuses what does not fit. */
export function laneSizeOk(width, height, size) {
  if (!size) return true;
  return width * height <= Number(size.max_area)
    && (size.ranges || []).some((r) => r[0] <= width && width <= r[1] && r[2] <= height && height <= r[3]);
}

/* Why switching the lane ON is refused right now, or null (C3): a reference picture, or a
   size over the lane's limit. The same sentence rides the switch's title, the line under it
   and -- while the lane is on -- the Generate gate. */
export function unlimitedBlock(s) {
  if (refSent(s)) return "Remove the reference picture to use Unlimited Mode";
  const size = laneSize(s.model);
  const d = dims(s);
  if (!laneSizeOk(d.width, d.height, size)) {
    return "Pick a smaller size to use Unlimited Mode — up to " + size.max_side + " × " + size.max_side;
  }
  return null;
}

/* Would this frame be refused on the lane? For the size stops and aspect glyphs while the
   switch is on: each is judged on the snapped dims() it would produce, never on its label. */
export function laneRefusesFrame(s, patch) {
  if (!s.unlimited) return false;
  const size = laneSize(s.model);
  if (!size) return false;
  const d = dims({ ...s, ...patch, customW: "", customH: "" });
  return !laneSizeOk(d.width, d.height, size);
}

/* Switching the lane ON sets what it runs on, visibly: Pro, one picture, no High priority.
   OFF touches nothing else -- only the user turns the lane off (§8.1). */
export function unlimitedPatch(on) {
  return on ? { unlimited: true, mode: "pro", count: 1, highPriority: false } : { unlimited: false };
}

/* The help mark's tooltip: the rules in one line. */
export function unlimitedRules(m) {
  const size = laneSize(m);
  return "Free Tsubaki.3 pictures while it lasts: Pro mode, one picture per run, no reference "
    + "picture" + (size ? ", up to " + size.max_side + " × " + size.max_side : "")
    + ", and one run at a time.";
}

/* "N days left", PixAI's own count (whole days, rounded up, from the server). */
export function unlimitedDaysText(m) {
  const n = Number(m && m.unlimited && m.unlimited.days_left);
  if (!(n > 0)) return "";
  return n === 1 ? "1 day left" : n + " days left";
}

/* C3b: the dock's own run list holds an Unlimited Mode task still waiting or running. The
   server stamps `lane` on the job when it submits one (and refuses a second itself). */
export function laneBusy(jobs) {
  return (jobs || []).some((j) => j && j.lane === "infinite"
    && ["done", "failed", "done_with_errors"].indexOf(j.status) === -1);
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

/* What the recipe row's fit check reads off the dock (lane w2-recipes, H decision 10 / T2b):
   the model, the prompt's length, and PixAI's own refusal on the dock's last price answer
   (`recipe_error`, keyed by the recipe ids it names). The row paints the same verdict. */
export function recipeFitCtx(s, priceAnswer, promptLen) {
  const refusals = {};
  const re = priceAnswer && priceAnswer.recipe_error;
  if (re) for (const id of re.recipe_ids || []) refusals[String(id)] = re;
  return {
    modelType: (s.model && s.model.model_type) || "",
    modelTitle: (s.model && s.model.title) || "",
    // Session M (review F7): a run's LONGEST resolved prompt when the dock passes one, since
    // a value drawn into one cell can take that cell over the recipes' budget.
    promptLen: promptLen != null ? promptLen : typeof s.prompt === "string" ? s.prompt.length : null,
    refusals,
  };
}

/* The Go gate, classic chain: resolved version + prompt + no unresolved/failed
   LoRA + no architecture mismatch + count within the account cap + no recipe that doesn't
   fit. `priceAnswer` (optional) is the dock's last /api/price answer, for PixAI's own recipe
   refusal; `promptLen` (optional) the longest resolved prompt of a run (Session M). */
export function goGate(s, loraCap, priceAnswer, promptLen) {
  if (!s.model || !s.model.version_id) return "Pick a model first";
  if (!s.prompt.trim()) return "Write a prompt";
  // The LoRA checks judge what is SENT: on the Context side the LoRAs are held, not sent.
  if (!onContextSide(s)) {
    if (s.loras.some((l) => l.failed)) return "A LoRA failed to resolve — remove it";
    if (s.loras.some((l) => !l.version_id)) return "A LoRA is still resolving";
    if (s.loras.some((l) => loraIncompat(l, s.model))) return "A LoRA does not match this model's architecture";
    if (loraCap != null && s.loras.length > loraCap) return "Over your LoRA cap (" + loraCap + ")";
    // Recipes, like the LoRAs, are judged only where they are SENT (the LoRA side); a recipe
    // that doesn't fit refuses in the row's own words (recipesCore.recipeGate, H T2b: "later
    // changes turn the chip peach and Generate refuses").
    const rg = recipeGate(s.recipes, recipeFitCtx(s, priceAnswer, promptLen));
    if (rg) return rg;
  }
  // Session H decision 1: the Context side sends its images and holds the rest. With no image
  // there is nothing of its own to send -- a plain run without the held LoRAs/recipes would be
  // a different picture than the one set up, so it waits.
  if (onContextSide(s)) {
    const ctx = s.ctx || [];
    if (!ctx.length) return "Add a context image — or switch back to LoRAs";
    const max = contextMax(s.model);
    if (ctx.length > max) return "Tsubaki.3 takes up to " + max + " context images — remove " + (ctx.length - max);
    // Decision 2: a chip whose image is gone reads peach "no image" and Generate refuses.
    const dead = deadRefs(s.prompt, ctx.length);
    if (dead.length) return dead[0] === "@image0" ? "A chip points at a removed image — fix or delete it"
      : dead[0] + " has no image — fix or delete it";
  }
  // T1a: a members-only profile is never picked for an account PixAI reports as non-member; one
  // carried in from a member session waits here rather than quoting a tier it can't run.
  const rows = profileRows(s.model);
  const picked = rows && rows.find((r) => String(r.name).toLowerCase() === String(s.mode || "").toLowerCase());
  if (picked && profileLocked(picked, s.member)) return (picked.title || picked.name) + " is for PixAI members — pick another profile";
  // Unlimited Mode on: what the server would refuse is refused here first, in its words. Not on
  // the Context side, where the lane is not sent at all (the row reads as a dashed line there).
  if (s.unlimited && !onContextSide(s)) return unlimitedBlock(s);
  return null;
}

/* THE payload builder -- one function feeds BOTH /api/price and /api/generate,
   the invariant the classic keeps (the quote and the spend cannot diverge). */
export function buildPayload(s) {
  const { width, height } = dims(s);
  const hires = s.boosters.hires && !(s.model && s.model.compat_upscale === false);
  // SCOPE_2026-09-26 G2/G3/G4 (owner ruling 1): what the drawer shows as not applying is
  // not sent. The chip STATE is kept across a model switch (never disarmed) -- only the
  // payload withholds it -- and a negative typed into a disabled box stays in the box,
  // unsent.
  const m = s.model;
  // Session H decision 1: the Context side sends its images and HOLDS the LoRAs, recipes,
  // palette and negative (kept in the state, not sent); the LoRA side never sends images.
  const ctxOn = onContextSide(s);
  const ctxIds = ctxOn ? (s.ctx || []).map((c) => c && c.media_id).filter(Boolean) : [];
  const recipeIds = !ctxOn ? (s.recipes || []).map((r) => r && r.id).filter(Boolean).map(String) : [];
  const creative = creativityModel(m);
  const noNeg = !!(m && m.compat_neg === false) || ctxOn;
  const face = !!s.boosters.face && !(m && m.compat_face === false);
  const quality = !!s.boosters.quality && !(m && m.compat_quality === false);
  // One effective steps value for BOTH steps and the mirrored denoise steps --
  // the classic sends its ||25 fallback to both (review: sending null to one and
  // a number to the other made the upscale pass stop mirroring sampling steps).
  const eff = s.steps === "" ? STEPS_FALLBACK : Number(s.steps);
  const palette = paletteForPayload(s, ctxOn);
  return {
    version_id: s.model ? s.model.version_id : "",
    model_id: s.model ? s.model.model_id : "",
    prompt: s.prompt,
    negative: noNeg ? "" : s.negative,
    width, height,
    mode: s.mode || "auto",
    steps: eff,
    cfg: s.cfg === "" ? null : Number(s.cfg),
    // Session M: a Matrix sends one image per cell (the page hides the count there).
    count: s.varMode === "matrix" ? 1 : Math.max(1, Math.min(4, Number(s.count) || 1)),
    seed: s.seed === "" ? null : s.seed,
    high_priority: !!s.highPriority,
    // Decision 5: on a creativity model the three stops replace the on/off helper; the
    // on/off still rides for the server's legacy fallback (off = "As written").
    prompt_helper: creative ? effectiveCreativity(s) !== "off" : !!s.promptHelper,
    ...(creative ? { creativity: effectiveCreativity(s) } : {}),
    ref_media_id: refSent(s) ? s.ref.media_id : null,
    ref_strength: refSent(s) ? Number(s.refStrength) : null,
    upscale: hires ? MG_HIRES.ratio : null,
    upscale_denoise: hires ? MG_HIRES.denoise : null,
    upscale_denoise_steps: hires ? eff : null,
    face_fix: face,
    // "Masterpiece" is the ON signal and the fallback: the server swaps in the chosen
    // version's own tag at build time (G4), and keeps this literal only when it could not
    // read the version row.
    quality_tag: quality ? "Masterpiece" : null,
    loras: ctxOn ? [] : s.loras.filter((l) => l.version_id)
      .map((l) => ({ version_id: l.version_id, weight: Number(l.weight) })),
    // Unlimited Mode: sent whenever the switch is on, offered or not (§8.1) -- the server
    // refuses what is not eligible; the drawer never drops the flag. Absent when off, so an
    // ordinary payload is byte-identical to before. The Context side does not send it: there
    // the row is the dashed "for runs without context images" line and the switch is kept.
    ...(s.unlimited && !ctxOn ? { unlimited: true } : {}),
    // The context images, in slot order (slot N is the prompt's @imageN) -- and the @imageN
    // numbers the prompt names, so an edit that changes them re-prices: the server refuses
    // a ref with no slot, and that verdict must never outlive the prompt it was reached on
    // (review B2). The server reads the prompt itself; this field only moves the identity.
    ...(ctxIds.length ? { context_images: ctxIds, image_refs: imageRefs(s.prompt) } : {}),
    // Recipes are lane w2-recipes'; the dock sends their ids on the LoRA side, never held ones.
    ...(recipeIds.length ? { recipeIds } : {}),
    // The colour palette (Session H 4, gen/colorPaletteCore.js): only with a palette applied,
    // a version whose /features lists colorPalette "on", and no context image -- the pick is
    // HELD otherwise, never cleared. Absent when it does not apply, so an ordinary payload is
    // byte-identical to before.
    ...(palette ? { color_palette: palette } : {}),
  };
}

/* The applied version's fields, as the drawer keeps them on `s.model` -- one function for
   the dock's applyModelRow/pickVersion (useGenerate.js) and the Lightbox edit bar's Tsubaki.3
   meta (TsubakiEditBar.jsx), so the bar's payload reads the version exactly as the dock does. */
export function versionPatch(v) {
  const patch = {
    caps: v.capabilities || [],
    compat_neg: cget(v, "negativePrompt"),
    compat_steps: cget(v, "samplingSteps"),
    compat_cfg: cget(v, "cfgScale"),
    compat_upscale: cget(v, "upscale"),
    // SCOPE_2026-09-26 (owner ruling 1): Face Fix and Quality Tag read disabled on a model
    // that does not take them. Face Fix through the same cget -- the server merges
    // /features' enableADetailer:false (and the MMDiT / user-DiT model-type rule) into
    // `compatibility`. Quality Tag from the version's own tag (G4): a row that answered
    // with no tag is false; a server without the field stays unknown (fail open).
    compat_face: cget(v, "enableADetailer"),
    compat_quality: "quality_tag" in v ? !!v.quality_tag : undefined,
    quality_tag: v.quality_tag || null,
    // The size rule the server's gate snaps to (G1) and whether a reference goes out as a
    // context image (G3). Set explicitly on EVERY apply, so a version picked from the list
    // without them (only the latest row carries them) never inherits the previous one's.
    size_rule: v.size_rule || null,
    context_images: v.context_images === true,
    // Whether this version takes a colour palette (Session H 4): true only when /features
    // lists colorPalette "on"; false when it answered without it; null when unread. The
    // palette is sent only on true (colorPaletteCore.paletteForPayload).
    color_palette: v.color_palette === true ? true : (v.color_palette === false ? false : null),
    // The inference profiles this VERSION offers, by profileName (SCOPE 2026-08-17 §4b).
    // null = the server could not determine them -> the drawer dims nothing, exactly as
    // before. An array (including []) is a real answer.
    profiles: Array.isArray(v.profiles) ? v.profiles : null,
    // Tsubaki.3 Unlimited Mode status for THIS version (SCOPE_2026-09-26_unlimited-mode S2),
    // set on every apply like size_rule. It only decides whether the switch is OFFERED: the
    // switch's own state (s.unlimited) survives a model switch -- only the user turns it off
    // (§8.1), and the server refuses a lane request this version cannot run.
    unlimited: v.unlimited || null,
    // Session H: the live size tiers (/size-config), the live context-image max
    // (/model-config), whether the helper is a creativity level, and the Pro / Ultra rows
    // (/inference-profiles). Set on every apply like size_rule -- a version picked from the
    // list without them (only the latest row carries them) never inherits the previous one's.
    size_tiers: Array.isArray(v.size_tiers) && v.size_tiers.length ? v.size_tiers : null,
    context_max: Number(v.context_max) > 0 ? Number(v.context_max) : null,
    creativity: v.creativity === true,
    profile_rows: Array.isArray(v.profile_rows) && v.profile_rows.length ? v.profile_rows : null,
    restrictions: v.restrictions || {},
    preset: {
      negative: v.negative_prompt || "", steps: v.sampling_steps,
      cfg: v.cfg_scale, sampler: v.sampling_method || "",
    },
  };
  return patch;
}

function cget(v, key) {
  const c = v.compatibility || {};
  return key in c ? c[key] : undefined; // undefined = unknown = fail-open
}

/* The @imageN numbers a prompt names, sorted and unique (the price identity's copy of them). */
export function imageRefs(prompt) {
  const out = new Set();
  const re = /@image(\d+)/g;
  let mm;
  while ((mm = re.exec(String(prompt || ""))) !== null) out.add(Number(mm[1]));
  return Array.from(out).sort((a, b) => a - b);
}

/* The Tsubaki edit's state (Session H decision 2's menu item prefills the dock with it; T3a's
   Lightbox bar builds its payload from it through buildPayload itself, so the bar can never
   send a shape the dock would not): Tsubaki.3's applied meta, the picture as context slot 1,
   Auto size, creativity medium, the given profile, count 1 -- and nothing else of the dock:
   no LoRAs, no recipes, no negative, no boosters, no High priority, a random seed. */
export function tsubakiEditState({ model, image, prompt, mode, tier, member }) {
  /* THE SIZE IS THE SOURCE PICTURE'S OWN (the owner's walk, 2026-10-03): PixAI's own Smart
     Reference submit sends the picture's width and height, not a size-tier area. It rides the
     dock's own custom-size road, so a source off the model's rule (its 16 px step, inside its
     range) is put on it exactly as a typed W x H is; an unknown size falls back to Auto. */
  const w = Math.round(Number(image && image.w) || 0), h = Math.round(Number(image && image.h) || 0);
  return {
    ...GEN_DEFAULTS, model, member: member === true ? true : member === false ? false : null,
    inputs: "context", ctxWarned: true, auto: true,
    customW: w > 0 && h > 0 ? String(w) : "", customH: w > 0 && h > 0 ? String(h) : "",
    ctx: image && image.media_id ? [{ media_id: String(image.media_id), thumb: image.thumb || "",
      w: Number(image.w) || 0, h: Number(image.h) || 0 }] : [],
    prompt: String(prompt || ""), mode: mode || "auto", tier: tier || "",
    count: 1, creativity: "medium", highPriority: false, negative: "", seed: "",
  };
}

/* A LoRA handed in from outside the dock's own picker (Train a LoRA's "Use", Training Handoff
   5c) goes on the LoRA side: on the Context side the LoRAs are held, not sent (buildPayload),
   so a LoRA added there would sit unseen and never run. This is the dock's state moved to the
   LoRA side -- its context images kept, held, exactly as the switch itself leaves them. */
export function toLoraSide(s) {
  return s && s.inputs !== "loras" ? { ...s, inputs: "loras" } : s;
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
  unlimited: false,     // Tsubaki.3 Unlimited Mode (SCOPE_2026-09-26_unlimited-mode C1)
  // ---- Session H (Tsubaki3 Generate Handoff) ----
  inputs: "loras",      // the LoRAs | Context images switch (decision 1)
  ctx: [],              // the context slots, in order: {media_id, thumb, w, h}
  ctxWarned: false,     // the confirm card shows on the first switch of a session only
  auto: true,           // Auto (size from @image1), the Frame row's first cell on the Context side
  landscape: false,     // the Portrait | Landscape switch (decision 7)
  tier: "",             // the picked live size tier ("" = the model's own default)
  creativity: "medium", // decision 5's stops (off | low | medium)
  recipes: [],          // lane w2-recipes' row: [{id, title, cover}]
  member: null,         // PixAI membership (true / false / null = unknown), from /api/account
  palette: null,        // the applied colour palette {name, palette, source, id, from} (Session H 4)
  // ---- Session M (Generate power tools) ----
  varMode: "random",    // Random (one value per image) | Matrix (every combination, cap 24)
  roll: 0,              // the run seed when the seed field is blank (useGenerate draws one)
  // NOTES 4: the base family the applied model belongs to (powerCore.familyOf), kept across a
  // model that is still resolving, so a family switch is compared with the family BEFORE it.
  family: "",
  note: "",             // the dock's one plain line after a default / Last / preset (cleared on typing)
};

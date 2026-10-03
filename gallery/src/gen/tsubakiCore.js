/* tsubakiCore.js -- the PURE half of Session H, Tsubaki.3 in the Generate drawer
   (moonglade-internal/design/handoff-2026-09-04/Tsubaki3 Generate Handoff.dc.html, decisions in
   design/notes/tsubaki3-generate/NOTES.md, the spend design in BUILD-w2-gen.md beside it).

   Imports nothing. genCore.js builds its dims / buildPayload / goGate on top of this; the dock
   (GenerateDrawer.jsx), the phone (CreateMobile.jsx) and the Lightbox edit bar only draw it.
   loom/test/tsubaki-core.test.js pins every rule here.

   What lives here:
     - the eleven ratios and the Portrait | Landscape switch (decision 7);
     - the model's live size tiers, the tier-dimension rule, Auto from @image1 and the
       account's custom-size limit (decisions 6 + 7, 6c);
     - the LoRAs | Context images switch: which side is live, what it holds, the confirm card's
       title (decision 1);
     - the @image grammar: dead refs, renumbering after a slot is removed, the seeded prompt
       (decision 2);
     - creativity stops (decision 5) and the Pro / Ultra rows (T1a). */

/* ---- ratios (decision 7) ----------------------------------------------------------------
   Landscape-first [a, b] with a >= b; the Portrait | Landscape switch flips every one. `src`
   is the dot the Frame slab draws: "web" = offered by PixAI, new to the app (lavender); "new" =
   offered by neither (emerald); "both" = no dot. Order and dots are the handoff page's RAT. */
export const RATIOS = [
  [1, 1, "both"], [5, 4, "new"], [9, 7, "web"], [4, 3, "both"], [3, 2, "both"], [5, 3, "web"],
  [16, 9, "both"], [2, 1, "new"], [21, 9, "new"], [3, 1, "both"], [4, 1, "new"],
];

/* The label a ratio wears in the given orientation: portrait reads short:long ("9:16"). */
export function ratioLabel(i, landscape) {
  const r = RATIOS[i];
  if (!r) return "";
  const [a, b] = r;
  return a === b ? "1:1" : landscape ? a + ":" + b : b + ":" + a;
}

/* width ÷ height for ratio i in the given orientation. */
export function ratioAspect(i, landscape) {
  const r = RATIOS[i];
  if (!r) return 1;
  const [a, b] = r;
  return landscape ? a / b : b / a;
}

/* Which of the eleven an aspect (w/h) is, or -1 (a custom or remixed size). */
export function ratioIndexOf(aspect) {
  const x = Number(aspect);
  if (!(x > 0)) return -1;
  for (let i = 0; i < RATIOS.length; i++) {
    const [a, b] = RATIOS[i];
    if (Math.abs(x - a / b) < 0.001 || Math.abs(x - b / a) < 0.001) return i;
  }
  return -1;
}

/* ---- the size grid (decisions 6 + 7) -----------------------------------------------------
   `m.size_tiers` is /api/model-version's live /size-config read (moonglade_backup
   _size_tiers_meta): [{name, min, max, step, required_tier, access, default: [w, h], presets:
   [{ratio: "3:5", width, height}]}], PixAI's own order (XL, L, M). Absent -> the model has no
   tiers and the dock keeps its long-edge stops. */

// Half-up onto the step: floor(x / step + 0.5) * step -- the server's _snap_size arithmetic.
export function snapHalfUp(x, step) {
  const s = Number(step) > 0 ? Number(step) : 16;
  return Math.floor(Number(x) / s + 0.5) * s;
}

export function sizeTiers(m) {
  return m && Array.isArray(m.size_tiers) && m.size_tiers.length ? m.size_tiers : null;
}

/* A tier is members-only when PixAI asks a membership tier for it or reports it unavailable to
   this account; it is LOCKED only for an account PixAI reports as non-member (an explicit
   false). Unknown membership fails open, like every members-only control in the app. */
export function tierMembersOnly(t) {
  return !!t && ((Number(t.required_tier) || 0) > 0 || (!!t.access && t.access !== "available"));
}
export function tierLocked(t, isMember) {
  return isMember === false && tierMembersOnly(t);
}

/* The tier actually in force: the picked one when the model has it and this account may use
   it, else the model's default (the first tier PixAI lists) when usable, else the first usable
   one. null for a model without tiers. */
export function effectiveTier(m, picked, isMember) {
  const tiers = sizeTiers(m);
  if (!tiers) return null;
  const usable = tiers.filter((t) => !tierLocked(t, isMember));
  const pool = usable.length ? usable : tiers;
  return pool.find((t) => t.name === picked) || pool[0];
}

/* The union of the tiers' ranges on the step (the server gate's own rule, _size_rule). */
export function tierUnion(m) {
  const tiers = sizeTiers(m);
  if (!tiers) return null;
  const step = Number(tiers[0].step) || 16;
  const lo = Math.min(...tiers.map((t) => Number(t.min) || 512));
  const hi = Math.max(...tiers.map((t) => Number(t.max) || 2048));
  return { step, lo: Math.ceil(lo / step) * step, hi: Math.floor(hi / step) * step };
}

/* The account's custom-size rule (6c: "clamped to your limit"): lo is the union's floor, hi the
   largest max side among the tiers this account may use. Null without tiers. */
export function accountSizeRule(m, isMember) {
  const tiers = sizeTiers(m);
  if (!tiers) return null;
  const u = tierUnion(m);
  const usable = tiers.filter((t) => !tierLocked(t, isMember));
  const pool = usable.length ? usable : tiers;
  const hi = Math.max(...pool.map((t) => Number(t.max) || u.hi));
  return { step: u.step, lo: u.lo, hi: Math.min(u.hi, Math.floor(hi / u.step) * u.step) };
}

/* Decision 7's rule for a ratio r >= 1 on a tier: area = the tier's default preset, long =
   √(area × r) on the step, capped at the tier's own max side; short = long ÷ r on the step. A
   short edge under the tier's floor holds at the floor and long = floor × r, capped at the
   model's union max -- "short edge held at 512". Returns {long, short, held}. */
function areaRule(tier, r, unionHi) {
  const step = Number(tier.step) || 16;
  const [dw, dh] = tier.default || [0, 0];
  const area = dw * dh;
  const floor = Math.ceil((Number(tier.min) || 512) / step) * step;
  const cap = Math.floor((Number(tier.max) || 2048) / step) * step;
  let long = snapHalfUp(Math.sqrt(area * r), step);
  if (long > cap) long = cap;
  let short = snapHalfUp(long / r, step);
  let held = false;
  if (short < floor) {
    short = floor;
    long = Math.min(Math.floor((unionHi || cap) / step) * step, snapHalfUp(floor * r, step));
    held = true;
  }
  return { long, short, held };
}

/* A ratio's size on a tier: PixAI's own preset when the tier's live grid has that ratio (the
   grid is labelled in portrait form), decision 7's area rule otherwise. {width, height, held,
   grid}. */
export function tierDims(m, tier, i, landscape) {
  const ratio = RATIOS[i] || RATIOS[0];
  const [a, b] = ratio;
  const portraitLabel = a === b ? "1:1" : b + ":" + a;
  const preset = (tier.presets || []).find((p) => p.ratio === portraitLabel);
  if (preset && preset.width > 0 && preset.height > 0) {
    const w = Number(preset.width), h = Number(preset.height);
    const pw = Math.min(w, h), ph = Math.max(w, h);    // portrait form
    return landscape && a !== b
      ? { width: ph, height: pw, held: false, grid: true }
      : { width: pw, height: ph, held: false, grid: true };
  }
  const u = tierUnion(m);
  const { long, short, held } = areaRule(tier, a / b, u && u.hi);
  return landscape ? { width: long, height: short, held, grid: false }
    : { width: short, height: long, held, grid: false };
}

/* Auto (decision 1): @image1's own aspect through the same area rule on the tier in force
   (dimmed on screen, still the area). {width, height, held} or null when image 1's size is
   not known. */
export function autoDims(m, tier, img) {
  const w = Number(img && img.w), h = Number(img && img.h);
  if (!(w > 0 && h > 0) || !tier) return null;
  const r = Math.max(w, h) / Math.min(w, h);
  const u = tierUnion(m);
  const { long, short, held } = areaRule(tier, r, u && u.hi);
  return w >= h ? { width: long, height: short, held } : { width: short, height: long, held };
}

/* The Lightbox edit bar sends the source picture's own size, as PixAI's own Smart Reference submit
   does (2026-10-03 capture) -- but only a size the site itself would send: both sides at most
   SOURCE_MAX_SIDE (the logged-in site's Tsubaki.3 model-config, 512-2048 a side;
   PROBE_2026-09-26_site) AND an area within the tier's own default preset (PixAI's largest presets
   are about 2 MP). An upscale or a 4K picture is neither, and goes back to Auto (autoDims). */
export const SOURCE_MAX_SIDE = 2048;
export function sourceSizeFits(m, tier, img) {
  const w = Number(img && img.w), h = Number(img && img.h);
  const t = tier || null;
  const [dw, dh] = (t && t.default) || [0, 0];
  if (!(w > 0 && h > 0) || !(dw > 0 && dh > 0)) return false;
  return w <= SOURCE_MAX_SIDE && h <= SOURCE_MAX_SIDE && w * h <= dw * dh;
}

/* ---- the LoRAs | Context images switch (decision 1) -------------------------------------- */

/* The Context side is live only on a version whose meta says a context image is taken
   (/features: MMDIT26B with contextImages on) -- anywhere else the old reference slot stays. */
export function contextModel(m) {
  return !!(m && m.context_images === true);
}
export function onContextSide(s) {
  return !!(s && s.inputs === "context" && contextModel(s.model));
}

/* Is Auto (size from @image1) ruling the frame? Only on the Context side, only while picked,
   and never beside a typed custom size (a custom W × H wins, as it does over every stop). */
export function autoActive(s) {
  const custom = !!(parseInt(s && s.customW, 10) > 0 && parseInt(s && s.customH, 10) > 0);
  return onContextSide(s) && s.auto !== false && !custom;
}

/* The live slot count (model-config's contextImages.maxCount; 3 when it could not be read). */
export function contextMax(m) {
  const n = Number(m && m.context_max);
  return n > 0 ? Math.floor(n) : 3;
}

/* What the Context side holds (set, kept, not sent), in the confirm card's order. The palette
   row is lane w2-small's; any truthy `palette` in the state counts. */
export function heldItems(s) {
  const out = [];
  if (s.loras && s.loras.length) out.push("lora");
  if (s.recipes && s.recipes.length) out.push("recipe");
  if (s.palette) out.push("palette");
  if (s.negative && String(s.negative).trim()) out.push("negative");
  return out;
}

const HELD_NOUN = {
  lora: "your LoRA", recipe: "your recipes", palette: "your palette", negative: "your negative prompt",
};
export function confirmTitle(held) {
  const lead = (held || [])[0];
  return "Switching holds " + (HELD_NOUN[lead] || "your picks");
}
export const CONFIRM_BODY = "Tsubaki.3 can't use LoRAs, a recipe, a palette or a negative prompt "
  + "with context images. They stay where they are and come back when you switch.";
export const HELD_NOTE = "Held · not sent with context images";

/* Does switching to the Context side need the confirm card first? Only the first switch of a
   session, and only while something would be held. */
export function needsSwitchConfirm(s) {
  return !s.ctxWarned && heldItems(s).length > 0;
}

/* ---- the @image grammar (decision 2) ----------------------------------------------------- */
export const AT_REF_RE = /@image(\d+)/g;
// A typed @image0 still names no slot (deadRefs); removing a slot no longer writes one.
export const DEAD_REF = "@image0";
export const SEED_PROMPT = "Use @image1 ";

/* The @imageN refs in `prompt` that point at no slot (N < 1, or N > count). */
export function deadRefs(prompt, count) {
  const out = [];
  const re = new RegExp(AT_REF_RE.source, "g");
  let mm;
  while ((mm = re.exec(String(prompt || ""))) !== null) {
    const n = Number(mm[1]);
    if (n < 1 || n > count) out.push("@image" + n);
  }
  return out;
}

/* Renumber after slot `k` (0-based) of `count` slots is removed (owner walk 2026-09-29: the old
   rule wrote "@image0" into the prompt, and it showed as raw text on the LoRAs side).
     - a ref to a picture past the removed one follows its picture down one (@image3 -> @image2);
     - a ref to the removed picture keeps pointing at NO picture, so it reads as the peach "no
       image" chip: it stays exactly as typed when that was the last slot, and otherwise takes
       the old last number (`count`) -- the one number nothing moved into, so it can never
       silently turn into the picture that slid into its place;
     - everything else -- refs before it, refs that already named no slot -- is left as typed.
   Never an index below 1. `count` absent reads as "the removed slot was the last one". */
export function renumberAfterRemove(prompt, k, count) {
  const last = Number(count) > k ? Math.floor(Number(count)) : k + 1;
  return String(prompt || "").replace(new RegExp(AT_REF_RE.source, "g"), (all, d) => {
    const n = Number(d);
    if (n === k + 1) return "@image" + last;
    if (n > k + 1 && n <= last) return "@image" + (n - 1);
    return all;
  });
}

/* ---- creativity (decision 5) ------------------------------------------------------------- */
export const CREATIVITY = [
  ["off", "As written", "Off · your prompt as written"],
  ["low", "Light touch", "Low · a light touch"],
  ["medium", "Embellished", "Medium · PixAI embellishes the prompt"],
];
export const CREATIVITY_DEFAULT = "medium";

/* The stops replace the Prompt helper switch on a version whose helper is a creativity level
   (MMDIT26B -- the meta's `creativity` flag). */
export function creativityModel(m) {
  return !!(m && m.creativity === true);
}
export function effectiveCreativity(s) {
  if (onContextSide(s)) return "medium";                    // set by context images
  const c = s && s.creativity;
  return CREATIVITY.some(([k]) => k === c) ? c : CREATIVITY_DEFAULT;
}
export function creativityName(level) {
  return (CREATIVITY.find(([k]) => k === level) || CREATIVITY[2])[1];
}

/* ---- Pro / Ultra rows (T1a) -------------------------------------------------------------- */
export function profileRows(m) {
  return m && Array.isArray(m.profile_rows) && m.profile_rows.length ? m.profile_rows : null;
}
export function profileLocked(row, isMember) {
  return isMember === false && !!row
    && (row.flag === "membershipOnly" || (Number(row.required_tier) || 0) > 0);
}
/* The row's "+N": its live basePrice over the default-flagged row's (what PixAI's picker
   shows). null when either price is missing. */
export function profileExtra(row, rows) {
  const def = (rows || []).find((r) => r.flag === "default") || (rows || [])[0];
  if (!row || !def) return null;
  const a = Number(row.base_price), b = Number(def.base_price);
  return isFinite(a) && isFinite(b) && row.base_price != null && def.base_price != null ? a - b : null;
}
/* Is `row` the one in force for `mode`? "auto" means the default-flagged row. */
export function profilePicked(row, rows, mode) {
  if (!row) return false;
  if (mode && mode !== "auto") return String(mode).toLowerCase() === String(row.name).toLowerCase();
  const def = (rows || []).find((r) => r.flag === "default") || (rows || [])[0];
  return !!def && def.name === row.name;
}

/* ---- the Tsubaki edit (decision 2's menu item and T3a's Lightbox bar) --------------------- */
/* The model a Tsubaki edit runs on. Mirrors moonglade_backup.TSUBAKI3_MODEL_ID /
   TSUBAKI3_VERSION_ID (tests/test_tsubaki3_generate.py pins the two copies together). The
   edit is offered on every still picture, whatever model made it (the card's tsubaki_edit). */
export const TSUBAKI3 = { model_id: "2024383378759147749", version_id: "2024383379556065549", title: "Tsubaki.3" };

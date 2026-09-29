/* THE RECIPES' PURE HALF (Session K + H3/H8/H10, lane w2-recipes, 2026-09-28).

   Everything the recipe surfaces decide that is worth pinning without a renderer: what a
   card says, whether a recipe fits the dock's request (H decision 10, T2b), what the
   creator still needs (H decision 8, K decision 4), the draft <-> PixAI body mapping, and
   the dock row's own refusal. It imports NOTHING, so loom/test/recipes-core.test.js runs it
   in plain node. The components (RecipeRow, RecipesOverlay, RecipeCreator, RecipesMobile)
   draw what this returns; moonglade_recipes.py is the server half (its refusal copy for
   PixAI's own 422s is the one home of those sentences -- this file only words what the
   client can see for itself: the model, the prompt budget and a card's usability). */

export const MAX_RECIPES = 10;
export const MAX_SLOTS = 8;
export const TITLE_MAX = 200;
export const DESCRIPTION_MAX = 2000;
export const SHOWCASE_MIN = 3;
export const SHOWCASE_MAX = 8;
export const TRIGGER_MAX = 512;
export const TEST_LIMIT = 100;   // "1 / 100 tests" (H §C2)

// The seven categories, in the handoff's order, with its one-line hints (H §C2 step 1).
export const CATEGORIES = [
  ["character", "Character", "Keeps the same character across results"],
  ["style", "Style", "Reproduces an art style"],
  ["pose", "Pose & Framing", "Fixes the pose or framing"],
  ["panel", "Manga Panel", "Lays out a multi-panel page"],
  ["effect", "Effect", "Adds a visual effect"],
  ["outfit", "Outfit", "Dresses the subject in an outfit"],
  ["scene", "Scene", "Places the subject in a setting"],
];
const CAT_LABEL = Object.fromEntries(CATEGORIES.map(([k, l]) => [k, l]));
export function categoryLabel(key) {
  if (!key) return "";
  return CAT_LABEL[key] || String(key).replace(/^\w/, (c) => c.toUpperCase());
}

export const MODEL_TYPE_LABELS = { MMDIT26B_MODEL: "DiT.3", MMDIT26A_MODEL: "DiT.2", SDXL_MODEL: "SDXL" };
export function modelTypeLabel(t) { return MODEL_TYPE_LABELS[t] || (t ? String(t).replace(/_MODEL$/, "") : ""); }

export const SORTS = [["trending", "Trending"], ["most-liked", "Most liked"], ["most-used", "Most used"], ["latest", "Latest"]];
export const TABS = [["market", "Market"], ["sets", "Sets"], ["mine", "Mine"], ["history", "History"]];

// Every ingredient kind PixAI's schema has, in K decision 4's order (context images, the
// schema's seventh kind, after reference images). Shown for every model, dimmed with the
// reason when the model doesn't take it, "so the list doesn't change shape between models".
export const KINDS = [
  { type: "promptFragment", name: "Prompt", src: "typed, or the dock's / the image's prompt" },
  { type: "lora", name: "LoRA · weight · trigger words", src: "the LoRA picker" },
  { type: "baseImage", name: "Base image · strength", src: "history · the gallery · upload" },
  { type: "referenceImages", name: "Reference images", src: "history · the gallery · image Collections" },
  { type: "contextImages", name: "Context images", src: "history · the gallery · upload" },
  { type: "styleCode", name: "Style code", src: "a legacy code, resolved to its recipe" },
  { type: "referenceVideos", name: "Reference videos", src: "your videos" },
];
const KIND_SHORT = { promptFragment: "Prompt", lora: "LoRA", baseImage: "Base image", referenceImages: "Reference",
  contextImages: "Context image", styleCode: "Style code", referenceVideos: "Video" };

// K decision 5. `unlisted` is a state PixAI sets, not one its update route takes (the
// route's presetType is public | follow_to_use | private, and the site's own form leaves it
// out for a recipe that reads unlisted) -- so the choice is drawn, and disabled with why.
export const VISIBILITIES = [
  { key: "public", name: "Public", desc: "Listed in the market after PixAI reviews it" },
  { key: "unlisted", name: "Unlisted", desc: "Anyone with the link can use it", off: "PixAI sets this itself; it can't be chosen here" },
  { key: "follow_to_use", name: "Followers", desc: "Everyone sees it; your followers can use it" },
  { key: "private", name: "Private", desc: "Only you" },
];

/** The prompt budget a model gives (the site's jr(): 10,000 on the DiT.2/3 families). */
export function promptLimit(modelType) {
  return /^(USER_)?(MM)?DIT26[AB]_MODEL$/.test(String(modelType || "")) ? 10000 : 4096;
}

/** The LoRA weight range per model type (the site's Fr(): 0-1.2 on DiT, -2..2 otherwise). */
export function loraWeightRange(modelType) {
  const dit = ["DIT7_MODEL", "DIT7B_MODEL", "MMDIT26A_MODEL", "MMDIT26B_MODEL", "USER_DIT26A_MODEL", "USER_DIT26B_MODEL"];
  return dit.includes(String(modelType || "")) ? { min: 0, max: 1.2 } : { min: -2, max: 2 };
}

/** 66.9k / 1.2k / 8 -- the handoff's compact counts. */
export function compact(n) {
  n = Number(n) || 0;
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "k";
  return String(n);
}

export function fmt(n) { return (Number(n) || 0).toLocaleString("en-US"); }

/** "Prompt · LoRA ×1" -- what a recipe adds, by kind only (never its prompt text). */
export function kindsText(kinds) {
  return (kinds || []).map((k) => kindLabel(k)).join(" · ");
}
export function kindLabel(k) {
  const base = KIND_SHORT[k.type] || k.label || k.type;
  if (k.type === "promptFragment" || k.type === "styleCode" || k.type === "baseImage") return base;
  return base + " ×" + (k.count || 1);
}

/** The chip the dock keeps for a recipe -- {id, title, cover} is the row's contract; the
    rest rides along so the row can check fit without a call (H decision 10: "the model
    from the list's own model field, with no call per tile"). */
export function chipOf(card) {
  const c = card || {};
  return {
    id: String(c.id || ""), title: c.title || "", cover: c.cover || "",
    model_type: c.model_type || "", model_title: c.model_title || "", model_id: c.model_id || "",
    prompt_len: Number(c.prompt_len) || 0, usability: c.usability || "",
    kinds: c.kinds || [],
  };
}

/** Add one recipe to the row: never twice, never past ten. Returns {list, refused}. */
export function addRecipe(list, card) {
  const cur = Array.isArray(list) ? list : [];
  const id = String((card && card.id) || "");
  if (!id) return { list: cur, refused: "That isn't a recipe" };
  if (cur.some((r) => String(r.id) === id)) return { list: cur, refused: "" };
  if (cur.length >= MAX_RECIPES) return { list: cur, refused: "Up to " + MAX_RECIPES + " recipes — remove one first" };
  return { list: [...cur, chipOf(card)], refused: "" };
}
export function removeRecipe(list, id) {
  return (Array.isArray(list) ? list : []).filter((r) => String(r.id) !== String(id));
}
export function hasRecipe(list, id) {
  return (Array.isArray(list) ? list : []).some((r) => String(r.id) === String(id));
}

/** Prompt characters the row's recipes add (their text specs' lengths). */
export function recipesPromptLen(list) {
  return (list || []).reduce((n, r) => n + (Number(r.prompt_len) || 0), 0);
}

/** Does `card` fit the dock's request? null when nothing the CLIENT can see says no, else
    {tag, why, fix, group}. `ctx`:
      modelType / modelTitle   the dock's model (the row's prop; the title when known)
      promptLen                the dock prompt's length, when the dock published it
      recipes                  the row's current chips (their prompts count against the budget)
      refusals                 {recipeId: refusal} from PixAI's own answer (a price check)
    The model check reads the card's own model field; same type but a different model is
    left to PixAI (a price check), never guessed. */
export function misfitOf(card, ctx) {
  const c = card || {};
  const x = ctx || {};
  const id = String(c.id || "");
  const ref = x.refusals && x.refusals[id];
  if (ref) return { tag: ref.tag || "Doesn't fit", why: ref.copy || "doesn't fit this request", fix: ref.fix || "Remove it", group: ref.group || "" };
  if (c.usability === "unavailable") {
    return { tag: "Unavailable", why: "This recipe isn't available any more", fix: "Remove", group: "unavailable" };
  }
  if (c.usability === "follow_required") {
    return { tag: "Followers only", why: "Follow the author to use it", fix: "Follow the author", group: "follow" };
  }
  if (c.model_type && x.modelType && c.model_type !== x.modelType) {
    const made = c.model_title || modelTypeLabel(c.model_type);
    const cur = x.modelTitle || modelTypeLabel(x.modelType);
    return { tag: "Needs " + made, why: "made for " + made + ", not " + cur, fix: "Switch the dock's model", group: "model" };
  }
  const others = (x.recipes || []).filter((r) => String(r.id) !== id);
  const need = (Number(x.promptLen) || 0) + recipesPromptLen(others) + (Number(c.prompt_len) || 0);
  const limit = promptLimit(x.modelType || c.model_type);
  if ((Number(c.prompt_len) || 0) > 0 && need > limit) {
    return { tag: "Prompt too long", why: "would make the prompt too long (" + fmt(need) + " / " + fmt(limit) + ")", fix: "Shorten the prompt", group: "prompt" };
  }
  return null;
}

/** The dock's own refusal for its recipe row, in the words Generate shows -- or null.
    w2-gen's Go gate may call this; the row paints the same verdict on the chips. */
export function recipeGate(list, ctx) {
  const cur = Array.isArray(list) ? list : [];
  if (!cur.length) return null;
  if (cur.length > MAX_RECIPES) return "Up to " + MAX_RECIPES + " recipes — remove " + (cur.length - MAX_RECIPES);
  const bad = cur.filter((r) => misfitOf(r, { ...(ctx || {}), recipes: cur }));
  if (!bad.length) return null;
  return bad.length === 1 ? "“" + (bad[0].title || "A recipe") + "” doesn't fit — fix or remove it"
    : bad.length + " recipes don't fit — fix or remove them";
}

/** The market card's "↗ 66.9k" / author / category badges, as text. */
export function authorName(card) {
  const c = card || {};
  if (c.official) return "PixAI Official";
  return (c.author && (c.author.name || c.author.username)) || "";
}

/** "Adds to the prompt: +86 chars · 1,240 / 10,000" (H §C's detail pane line). */
export function promptAddLine(card, ctx) {
  const add = Number((card || {}).prompt_len) || 0;
  const x = ctx || {};
  const limit = promptLimit(x.modelType || (card || {}).model_type);
  if (x.promptLen == null) return "+" + fmt(add) + " chars";
  const total = (Number(x.promptLen) || 0) + recipesPromptLen((x.recipes || []).filter((r) => String(r.id) !== String(card.id))) + add;
  return "+" + fmt(add) + " chars · " + fmt(total) + " / " + fmt(limit);
}

// ------------------------------------------------------------------------------------------
// The creator's draft (the app's own until the user publishes -- nothing writes on open)
// ------------------------------------------------------------------------------------------

/** A fresh draft. `from` fills what K decision 4 prefills from a picture; `dock` what H
    §C2 presets from the dock (model and prompt). The category is never guessed. */
export function newDraft({ id, now, model, prompt, from } = {}) {
  const f = from || {};
  const m = model || {};
  const loras = (f.loras || []).filter((l) => l && l.version_id).map((l) => ({
    version_id: String(l.version_id), model_id: String(l.model_id || ""), title: l.title || "",
    weight: Number(l.weight), trigger_words: String(l.trigger_words || "").slice(0, TRIGGER_MAX),
  }));
  return {
    id: id || "", v: 1, created: now || 0, saved: now || 0,
    recipe_id: "", step: f.media_id ? 2 : 1,
    model: { model_id: String(m.model_id || f.model_id || ""), model_type: String(m.model_type || f.model_type || ""),
      title: m.title || f.model_title || "", version_id: String(m.version_id || f.version_id || "") },
    category: "",
    ingredients: loras.length ? [{ type: "lora", loras }] : [],
    test: { prompt: String(f.prompt || prompt || ""), ratio: "3:5", tier: "M", batch: 4 },
    showcase: f.media_id ? [{ media_id: String(f.media_id), thumb: f.thumb || "" }] : [],
    title: "", description: "", cover: "", preset: "public",
  };
}

/** How many items of `type` the draft holds (images in an image slot, LoRAs, fragments). */
export function kindCount(draft, type) {
  let n = 0;
  for (const g of (draft && draft.ingredients) || []) {
    if (g.type !== type) continue;
    if (type === "lora") n += (g.loras || []).length;
    else if (type === "referenceImages" || type === "contextImages") n += (g.images || []).length;
    else if (type === "referenceVideos") n += (g.videos || []).length;
    else n += 1;
  }
  return n;
}

/** {type: max} from /api/recipes/capability's {slots: [{type, max}]}. */
export function capsOf(capability) {
  const out = {};
  for (const s of (capability && capability.slots) || []) if (s && s.type) out[s.type] = Number(s.max) || 0;
  return out;
}

/** The "+ Add ingredient" menu: every kind, with its live count and why it's off. */
export function kindMenu(draft, capability) {
  const caps = capsOf(capability);
  const known = !!(capability && capability.slots);
  const slots = ((draft && draft.ingredients) || []).length;
  const types = new Set(((draft && draft.ingredients) || []).map((g) => g.type));
  return KINDS.map((k) => {
    const max = caps[k.type] || 0;
    const count = kindCount(draft, k.type);
    let off = "";
    if (!known) off = "reading what this model takes…";
    else if (!max) off = "not taken by " + ((draft && draft.model && draft.model.title) || "this model");
    else if (count >= max) off = "the model's limit is " + max;
    else if (slots >= MAX_SLOTS && !types.has(k.type)) off = "a recipe holds up to " + MAX_SLOTS + " ingredients";
    else if (k.type === "contextImages" && (types.has("lora") || types.has("baseImage"))) off = "can't go with a LoRA or a base image";
    else if ((k.type === "lora" || k.type === "baseImage") && types.has("contextImages")) off = "can't go with context images";
    return { ...k, max, count, off, text: max ? count + " / " + max : "—" };
  });
}

/** Every "Still needed" for a step, in the creator's own peach copy. [] when done. */
export function stillNeeded(draft, step) {
  const d = draft || {};
  const out = [];
  if (step === 1) {
    if (!d.model || !d.model.model_id || !d.model.model_type) out.push("a model");
    if (!d.category) out.push("a category");
    return out;
  }
  if (step === 2) {
    const ing = d.ingredients || [];
    if (!ing.length) out.push("an ingredient");
    const wr = loraWeightRange(d.model && d.model.model_type);
    for (const g of ing) {
      if (g.type === "promptFragment" && !String(g.text || "").trim()) { out.push("text in the prompt ingredient"); break; }
      if (g.type === "styleCode" && !String(g.code || "").trim()) { out.push("the style code"); break; }
      if (g.type === "lora") {
        if (!(g.loras || []).length) { out.push("a LoRA in the LoRA ingredient"); break; }
        if ((g.loras || []).some((l) => !(l.weight >= wr.min && l.weight <= wr.max))) { out.push("LoRA weights between " + wr.min + " and " + wr.max); break; }
      }
      if ((g.type === "referenceImages" || g.type === "contextImages") && !(g.images || []).length) { out.push("a picture in the image ingredient"); break; }
      if (g.type === "baseImage" && !(g.image && g.image.media_id)) { out.push("the base image"); break; }
    }
    const n = (d.showcase || []).length;
    if (n < SHOWCASE_MIN) {
      const more = SHOWCASE_MIN - n;
      out.push((n ? more + " more" : more) + " showcase image" + (more === 1 ? "" : "s"));
    }
    return out;
  }
  if (step === 3) {
    if (!String(d.title || "").trim()) out.push("a title");
    if (String(d.title || "").length > TITLE_MAX) out.push("a shorter title");
    if (String(d.description || "").length > DESCRIPTION_MAX) out.push("a shorter description");
    return out;
  }
  return out;
}

/** The first step with something still needed (3 when all are done). */
export function firstOpenStep(draft) {
  for (const s of [1, 2, 3]) if (stillNeeded(draft, s).length) return s;
  return 3;
}

/** "Still needed: 2 more showcase images" -- the footer's peach line ("" when done). */
export function neededLine(list) {
  return list && list.length ? "Still needed: " + list.join(", ") : "";
}

/** The Mine shelf's line for a draft: "Draft · step 2 of 3 · still needed: …". */
export function shelfLine(draft) {
  const s = firstOpenStep(draft);
  const need = stillNeeded(draft, s);
  return "Draft · step " + s + " of 3" + (need.length ? " · still needed: " + need.join(", ") : " · ready to publish");
}

/** "saved 2 h ago" -- relative, coarse, from epoch ms. */
export function savedAgo(ts, now) {
  const d = Math.max(0, ((now || 0) - (ts || 0)) / 1000);
  if (!ts) return "";
  if (d < 60) return "saved just now";
  if (d < 3600) return "saved " + Math.floor(d / 60) + " min ago";
  if (d < 86400) return "saved " + Math.floor(d / 3600) + " h ago";
  return "saved " + Math.floor(d / 86400) + " d ago";
}

/** The body the server's publish/update routes take (moonglade_recipes.update_body reads
    it): PixAI's slot shapes, one slot per ingredient, in order. */
export function toServerDraft(draft) {
  const d = draft || {};
  const slots = [];
  for (const g of d.ingredients || []) {
    if (g.type === "promptFragment") slots.push({ type: "promptFragment", text: String(g.text || "") });
    else if (g.type === "lora") slots.push({ type: "lora", loras: (g.loras || []).map((l) => {
      const o = { versionId: String(l.version_id), weight: Number(l.weight) };
      const tw = String(l.trigger_words || "").trim();
      if (tw) o.triggerWords = tw.slice(0, TRIGGER_MAX);
      return o;
    }) });
    else if (g.type === "baseImage") {
      const o = { type: "baseImage", image: { mediaId: String((g.image && g.image.media_id) || "") } };
      if (g.strength != null && g.strength !== "") o.strength = Number(g.strength);
      slots.push(o);
    } else if (g.type === "referenceImages") slots.push({ type: "referenceImages", images: (g.images || []).map((m) => ({ mediaId: String(m.media_id) })) });
    else if (g.type === "contextImages") slots.push({ type: "contextImages", images: (g.images || []).map((m) => {
      const o = { mediaId: String(m.media_id) };
      if (m.role) o.role = m.role;
      return o;
    }) });
    else if (g.type === "styleCode") slots.push({ type: "styleCode", styleCode: String(g.code || "").trim() });
    else if (g.type === "referenceVideos") slots.push({ type: "referenceVideos", videos: (g.videos || []).map((v) => ({ mediaId: String(v.media_id), durationSeconds: Number(v.duration) || 1 })) });
  }
  const showcase = (d.showcase || []).map((s) => String(s.media_id)).filter(Boolean).slice(0, SHOWCASE_MAX);
  const cover = d.cover && showcase.includes(String(d.cover)) ? String(d.cover) : (showcase[0] || "");
  return {
    categories: d.category ? [d.category] : [],
    modelType: (d.model && d.model.model_type) || "", modelId: (d.model && d.model.model_id) || "",
    title: String(d.title || "").trim(), description: String(d.description || ""),
    coverMediaId: d.cover && !showcase.includes(String(d.cover)) ? String(d.cover) : cover,
    showcaseMediaIds: showcase, presetType: d.preset || "public", slots,
  };
}

/** A published recipe (the owner's view, which carries its slots) back into a draft, so
    Mine's Edit opens the creator with the saved values. */
export function draftFromRecipe(card, { id, now } = {}) {
  const c = card || {};
  const ingredients = [];
  for (const s of c.slots || []) {
    if (!s || !s.type) continue;
    if (s.type === "promptFragment") ingredients.push({ type: "promptFragment", text: s.text || "" });
    else if (s.type === "lora") ingredients.push({ type: "lora", loras: (s.loras || []).map((l) => ({
      version_id: String(l.versionId), model_id: "", title: "", weight: Number(l.weight), trigger_words: l.triggerWords || "" })) });
    else if (s.type === "baseImage") ingredients.push({ type: "baseImage", image: { media_id: String((s.image || {}).mediaId || ""), thumb: "" }, strength: s.strength });
    else if (s.type === "referenceImages" || s.type === "contextImages") ingredients.push({ type: s.type, images: (s.images || []).map((m) => ({ media_id: String(m.mediaId), thumb: "", role: m.role })) });
    else if (s.type === "styleCode") ingredients.push({ type: "styleCode", code: s.styleCode || "" });
    else if (s.type === "referenceVideos") ingredients.push({ type: "referenceVideos", videos: (s.videos || []).map((v) => ({ media_id: String(v.mediaId), duration: v.durationSeconds })) });
  }
  const showcase = (c.showcase_media_ids || []).map((m) => ({ media_id: String(m), thumb: "" }));
  return {
    id: id || "", v: 1, created: now || 0, saved: now || 0, recipe_id: String(c.id || ""), editing: true,
    step: 1,
    model: { model_id: c.model_id || "", model_type: c.model_type || "", title: c.model_title || "", version_id: c.model_version_id || "" },
    category: c.category || "", ingredients,
    test: { prompt: "", ratio: "3:5", tier: "M", batch: 4 },
    showcase, title: c.title || "", description: c.description || "",
    cover: c.cover_media_id || "", preset: c.preset_type || "public",
  };
}

// ------------------------------------------------------------------------------------------
// Sizes for the test run (H decision 7's rule, the Tsubaki.3 sample tiers)
// ------------------------------------------------------------------------------------------

export const TEST_RATIOS = ["1:1", "3:4", "4:3", "3:5", "5:3", "9:16", "16:9"];
export const TIERS = { XL: [1104, 1824], L: [944, 1584], M: [768, 1280] };

/** W × H for a ratio "a:b" (a = width) in a tier: long = √(area × r) snapped to 16 and
    capped at the tier's long edge; short = long ÷ r snapped (H decision 7). */
export function tierDims(ratio, tier) {
  const [tw, th] = TIERS[tier] || TIERS.M;
  const [a, b] = String(ratio || "1:1").split(":").map(Number);
  const r = (a && b) ? Math.max(a, b) / Math.min(a, b) : 1;
  const cap = Math.max(tw, th);
  const snap = (v) => Math.max(16, Math.round(v / 16) * 16);
  let long = Math.min(cap, snap(Math.sqrt(tw * th * r)));
  let short = snap(long / r);
  if (short < 512) { short = 512; long = snap(512 * r); }
  return a >= b ? { width: long, height: short } : { width: short, height: long };
}

/** The price payload for the creator's (unwired) test run: the model, the test prompt, the
    frame, the batch, and the draft's LoRAs folded in as LoRAs -- the way the site's own
    pricing folds a recipe's LoRAs in. An approximation, drawn with "≈". */
export function testPricePayload(draft) {
  const d = draft || {};
  const t = d.test || {};
  const { width, height } = tierDims(t.ratio, t.tier);
  const loras = [];
  for (const g of d.ingredients || []) {
    if (g.type === "lora") for (const l of g.loras || []) loras.push({ version_id: l.version_id, weight: Number(l.weight) });
  }
  return {
    version_id: (d.model && d.model.version_id) || "", model_id: (d.model && d.model.model_id) || "",
    prompt: String(t.prompt || "") || "test", negative: "", width, height, mode: "auto",
    count: Number(t.batch) === 1 ? 1 : 4, loras,
  };
}

// ------------------------------------------------------------------------------------------
// Market queries
// ------------------------------------------------------------------------------------------

/** The market's query for a state: search wins over sort (PixAI's search is newest-first). */
export function marketQuery({ sort, category, modelType, q, page } = {}) {
  const out = { sort: sort || "trending", page: page || 1, page_size: 24 };
  if (category) out.category = category;
  if (modelType) out.model_type = modelType;
  if (q && String(q).trim()) out.q = String(q).trim().slice(0, 100);
  return out;
}

/** The active-filter chips ("Model: DiT.3", "Style"). */
export function filterChips({ category, modelType } = {}) {
  const out = [];
  if (category) out.push({ key: "category", text: categoryLabel(category) });
  if (modelType) out.push({ key: "modelType", text: "Model: " + modelTypeLabel(modelType) });
  return out;
}

/** Mine's status pill: [label, tone] -- Published emerald · Test/in review lavender · Archived. */
export function statusPill(status) {
  if (status === "published") return ["Published", "emerald"];
  if (status === "test") return ["In review", "lavender"];
  if (status === "archived") return ["Archived", "muted"];
  if (status === "draft") return ["Draft", "peach"];
  return [status || "—", "muted"];
}
export function statusAction(status) {
  if (status === "published") return "Edit";
  if (status === "test") return "View";
  if (status === "archived") return "Unarchive";
  return "View";
}

/** A draft id that is a valid prefs key segment: "d" + base36 time + a random tail. */
export function draftId(now, rand) {
  return "d" + Math.floor(now || 0).toString(36) + (rand || "").toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 6);
}
export const DRAFT_PREFIX = "recipes.draft.";
export function draftsFromPrefs(prefs) {
  const out = [];
  for (const k of Object.keys(prefs || {})) {
    if (k.startsWith(DRAFT_PREFIX) && prefs[k] && typeof prefs[k] === "object") out.push(prefs[k]);
  }
  return out.sort((a, b) => (b.saved || 0) - (a.saved || 0));
}

/* The Generate dock's power tools that live on the ACCOUNT (Session M, Generate power tools,
   NOTES 4, 5 and 6; Generate Power Tools Handoff, frame A and its rules M2, M3 and M4):

     - the default negative per base family (a saved negative per family, filled in when a
       family is picked and the field is empty or still the old default);
     - ↺ Last and Presets (the composer's fields, minus the seed for a preset);
     - the quick-pick chips (3 recent + starred favourites per row, at most 6).

   PURE: imports nothing, so loom/test/power-core.test.js runs exactly what the dock renders.
   useGenerate.js does the reading and writing through the wave-1 account store
   (/api/account/prefs, one JSON value per key, 64 KB each); the components only draw. Four keys,
   all under the dock's own `gen.` segment beside gen.image and gen.lists:

     gen.negatives   {family: negative text}
     gen.presets     [{name, ...snapshot}]                    30 at most
     gen.last        snapshot + seed                          the last SUCCESSFUL send
     gen.quick       {models: {recent, fav}, loras: {recent, fav}, weights}

   Everything read back is checked: a value of the wrong shape is dropped, never repaired into
   something the owner did not pick (the rule genPrefs.js sets for gen.image). Nothing here is
   ever written by opening the dock: the store is written by a deliberate click (Save, ★,
   Set as default) or by a send that the server accepted. */

export const NEG_KEY = "gen.negatives";
export const PRESETS_KEY = "gen.presets";
export const LAST_KEY = "gen.last";
export const QUICK_KEY = "gen.quick";

export const PRESET_MAX = 30;
export const PRESET_NAME_MAX = 60;
export const NEG_MAX = 2000;
export const PROMPT_MAX = 8000;
export const QUICK_RECENT = 3;
export const QUICK_ROW_MAX = 6;
export const QUICK_FAV_MAX = 24;
export const LORA_KEEP_MAX = 20;
/* A preference value is capped at 64 KB by the server; a save that would come near it is
   refused in plain words instead of being sent to fail. */
export const PREF_SOFT_LIMIT = 56 * 1024;

/* ---- families (NOTES 4) --------------------------------------------------------------- */

export const FAMILIES = ["DiT", "SDXL", "SD 1.5", "Pony", "Illustrious", "Flux"];

/* The base a model card names ("Pony", "Illustrious", "Flux", "SDXL", "SD 1.5"), read from
   the marketplace's own base_model category; "" when it says nothing usable. Same reading as
   the picker's baseLabel. */
export function baseHintOf(baseModel) {
  const cat = String(baseModel || "").replace(/^uploaded-/, "").replace(/[-_]+/g, " ").trim();
  if (!cat) return "";
  if (/sdxl/i.test(cat)) return "SDXL";
  if (/^sd ?v?1/i.test(cat)) return "SD 1.5";
  if (/flux/i.test(cat)) return "Flux";
  if (/pony/i.test(cat)) return "Pony";
  if (/illustrious/i.test(cat)) return "Illustrious";
  return "";
}

/* A base family for the default negative: "Pony", "Illustrious" and "Flux" only when the
   model card said so; otherwise the architecture PixAI reports (DiT, SDXL, SD 1.5). "" while
   nothing is known (a model still resolving) -- and then no default is touched. */
export function familyOf(model) {
  if (!model) return "";
  const hint = FAMILIES.includes(model.base_hint) ? model.base_hint : "";
  if (hint === "Pony" || hint === "Illustrious" || hint === "Flux") return hint;
  const t = String(model.model_type || "").toUpperCase();
  if (t.includes("DIT")) return "DiT";
  if (t.includes("SDXL")) return "SDXL";
  if (t.includes("SD_V1")) return "SD 1.5";
  return hint;
}

/* PixAI's architecture names, for a chip's reason ("for DiT.3 models"). */
const ARCH = {
  MMDIT26B_MODEL: "DiT.3", MMDIT26A_MODEL: "DiT.2", DIT7_MODEL: "DiT.1", DIT7B_MODEL: "DiT.1",
  SDXL_MODEL: "SDXL", SD_V1_MODEL: "SD 1.5", USER_DIT26B_MODEL: "Comm.DiT", USER_DIT26A_MODEL: "Comm.DiT",
};
export function archName(type) {
  return ARCH[String(type || "").toUpperCase()] || "";
}

/* gen.negatives as it comes back: {family: text}, known families only, each text bounded. */
export function defaultsFromPrefs(v) {
  const out = {};
  if (!v || typeof v !== "object" || Array.isArray(v)) return out;
  for (const f of FAMILIES) {
    const t = v[f];
    if (typeof t === "string" && t.trim() && t.length <= NEG_MAX) out[f] = t;
  }
  return out;
}

/* THE FILL RULE (page M2, setBase): on a family switch -- and on the first model of a
   session, `from` being "" -- the negative becomes the new family's default when the field is
   empty or still holds the OLD family's default. A negative the owner typed is never replaced.
   -> {negative, note}. An author preset is applied AFTER this by the caller (it still wins). */
export function negativeOnSwitch({ from, to, negative, defaults }) {
  const cur = String(negative == null ? "" : negative);
  const d = defaults || {};
  if (!to || from === to) return { negative: cur, note: "" };
  const oldDefault = from ? d[from] || "" : "";
  const empty = !cur.trim();
  const still = !!oldDefault && cur === oldDefault;
  if (!empty && !still) return { negative: cur, note: "" };
  const next = d[to] || "";
  if (!from) {
    return next ? { negative: next, note: "Started with your " + to + " default negative." }
      : { negative: cur, note: "" };
  }
  return {
    negative: next,
    note: next ? "Switched to " + to + ": its default negative is filled in."
      : "Switched to " + to + ": no default saved for it.",
  };
}

/* The ☆ Set as default | ★ Default button's state (page: isDefault, defaultLabel). */
export function defaultState({ family, negative, defaults }) {
  const isDefault = !!family && !!negative && negative === (defaults || {})[family];
  return {
    isDefault,
    label: isDefault ? "★ Default · " + family : "☆ Set as default",
    title: !family ? "Pick a model first — a default belongs to a base family"
      : isDefault ? "Click to reset (clear) the " + family + " default"
        : negative ? "Use this negative by default for " + family + " models"
          : "Type a negative first",
    disabled: !family || (!isDefault && !String(negative || "").trim()),
  };
}

/* Clicking it (page: toggleDefault). -> {defaults, note} or {error}. */
export function toggleDefault({ family, negative, defaults }) {
  if (!family) return { error: "Pick a model first — a default belongs to a base family." };
  const cur = defaults || {};
  const st = defaultState({ family, negative, defaults: cur });
  const next = { ...cur };
  if (st.isDefault) {
    delete next[family];
    return { defaults: next, note: "The " + family + " default is cleared." };
  }
  const t = String(negative || "");
  if (!t.trim()) return { error: "Type a negative first." };
  if (t.length > NEG_MAX) return { error: "A default negative is up to " + NEG_MAX + " characters." };
  next[family] = t;
  return { defaults: next, note: "Saved as the " + family + " default. New sessions start with it." };
}

/* The model row's preset note gets the page's tail when an author preset carries a negative
   and a default would have been used ("…and a negative prompt (replaces your default)"). */
export function presetNegativeTail(model, defaults) {
  const fam = familyOf(model);
  const hasNeg = !!(model && model.preset && String(model.preset.negative || "").trim());
  return hasNeg && fam && (defaults || {})[fam] ? " · and a negative prompt (replaces your default)" : "";
}

/* ---- snapshots: ↺ Last and Presets (NOTES 5) ------------------------------------------- */

const LEVELS = ["off", "low", "medium"];
const MODES = ["auto", "lite", "standard", "pro", "ultra", "flash"];
const VAR_MODES = ["random", "matrix"];
/* PixAI ids are digit strings; the looser rule only keeps a plain token out of the store. */
const ID_RE = /^[A-Za-z0-9_-]{1,64}$/;
const str = (v, max) => (typeof v === "string" ? v.slice(0, max) : "");
const num = (v, lo, hi) => (typeof v === "number" && isFinite(v) && v >= lo && v <= hi ? v : null);
const digits = (v, max) => (typeof v === "string" && /^\d*$/.test(v) ? v.slice(0, max) : "");

/* The composer's fields, as a plain object the account can hold: the tab (Image -- the only
   tab that carries a template), the model, the LoRAs with their weights, the prompt template,
   the negative, the frame, the count, Random | Matrix, the profile, steps and CFG, and the
   toggles. The seed is NOT part of it (a preset never stores it); Last adds it. */
export function snapshotOf(s, opts) {
  const m = s && s.model;
  const snap = {
    tab: "image",
    model: m && m.model_id ? {
      model_id: String(m.model_id), title: str(m.title, 200), thumb: str(m.thumb, 2048),
      version_id: str(String(m.version_id || ""), 64), model_type: str(m.model_type, 64),
      base_hint: FAMILIES.includes(m.base_hint) ? m.base_hint : "",
    } : null,
    loras: ((s && s.loras) || []).filter((l) => l && l.model_id).slice(0, LORA_KEEP_MAX).map((l) => ({
      model_id: String(l.model_id), title: str(l.title, 200), preview_url: str(l.preview_url, 2048),
      version_id: str(String(l.version_id || ""), 64), weight: Number(l.weight),
      lora_base_type: str(l.lora_base_type, 64), trigger_words: str(l.trigger_words, 500),
    })),
    prompt: str(s && s.prompt, PROMPT_MAX),
    negative: str(s && s.negative, NEG_MAX * 2),
    aspect: Number(s && s.aspect) || 1,
    size: Number(s && s.size) || 1024,
    customW: digits(s && s.customW, 5),
    customH: digits(s && s.customH, 5),
    landscape: !!(s && s.landscape),
    tier: str(s && s.tier, 8),
    auto: !s || s.auto !== false,
    steps: str(String(s && s.steps != null ? s.steps : ""), 6),
    cfg: str(String(s && s.cfg != null ? s.cfg : ""), 8),
    count: Math.max(1, Math.min(4, Number(s && s.count) || 1)),
    varMode: VAR_MODES.includes(s && s.varMode) ? s.varMode : "random",
    mode: MODES.includes(s && s.mode) ? s.mode : "auto",
    creativity: LEVELS.includes(s && s.creativity) ? s.creativity : "medium",
    highPriority: !!(s && s.highPriority),
    promptHelper: !s || s.promptHelper !== false,
    boosters: {
      face: !!(s && s.boosters && s.boosters.face), quality: !!(s && s.boosters && s.boosters.quality),
      hires: !!(s && s.boosters && s.boosters.hires),
    },
  };
  if (opts && opts.withSeed) snap.seed = str(String(s && s.seed != null ? s.seed : ""), 12);
  return snap;
}

/* A stored snapshot, checked field by field; null when it is not one. */
export function snapshotFrom(v) {
  if (!v || typeof v !== "object" || Array.isArray(v)) return null;
  const m = v.model && typeof v.model === "object" && !Array.isArray(v.model) && v.model.model_id
    && ID_RE.test(String(v.model.model_id)) ? {
      model_id: String(v.model.model_id), title: str(v.model.title, 200), thumb: str(v.model.thumb, 2048),
      version_id: str(String(v.model.version_id || ""), 64), model_type: str(v.model.model_type, 64),
      base_hint: FAMILIES.includes(v.model.base_hint) ? v.model.base_hint : "",
    } : null;
  const loras = Array.isArray(v.loras) ? v.loras.filter((l) => l && typeof l === "object"
    && ID_RE.test(String(l.model_id || "")) && num(Number(l.weight), -10, 10) !== null)
    .slice(0, LORA_KEEP_MAX).map((l) => ({
      model_id: String(l.model_id), title: str(l.title, 200), preview_url: str(l.preview_url, 2048),
      version_id: str(String(l.version_id || ""), 64), weight: Number(l.weight),
      lora_base_type: str(l.lora_base_type, 64), trigger_words: str(l.trigger_words, 500),
    })) : [];
  const b = v.boosters && typeof v.boosters === "object" ? v.boosters : {};
  const snap = {
    tab: "image", model: m, loras,
    prompt: str(v.prompt, PROMPT_MAX), negative: str(v.negative, NEG_MAX * 2),
    aspect: num(v.aspect, 0.2, 5) || 1, size: num(v.size, 64, 8192) || 1024,
    customW: digits(v.customW, 5), customH: digits(v.customH, 5),
    landscape: v.landscape === true, tier: /^[A-Za-z0-9]{0,8}$/.test(v.tier || "") ? String(v.tier || "") : "",
    auto: v.auto !== false,
    steps: /^\d{0,4}$/.test(String(v.steps == null ? "" : v.steps)) ? String(v.steps == null ? "" : v.steps) : "",
    cfg: /^\d{0,3}(\.\d{0,2})?$/.test(String(v.cfg == null ? "" : v.cfg)) ? String(v.cfg == null ? "" : v.cfg) : "",
    count: Math.max(1, Math.min(4, Math.trunc(Number(v.count)) || 1)),
    varMode: VAR_MODES.includes(v.varMode) ? v.varMode : "random",
    mode: MODES.includes(v.mode) ? v.mode : "auto",
    creativity: LEVELS.includes(v.creativity) ? v.creativity : "medium",
    highPriority: v.highPriority === true, promptHelper: v.promptHelper !== false,
    boosters: { face: b.face === true, quality: b.quality === true, hires: b.hires === true },
  };
  if (typeof v.seed === "string") snap.seed = /^-?\d{0,12}$/.test(v.seed) ? v.seed : "";
  return snap;
}

/* The state patch a restore writes for everything that is not the model, the LoRAs or the
   profile mode (those need the applied model and are the hook's). Never the seed unless it
   is asked for (↺ Last); ctx images, the reference, the palette and the recipes are not part
   of a snapshot and are left as they are. */
export function restorePatch(snap, opts) {
  const p = {
    prompt: snap.prompt, negative: snap.negative,
    aspect: snap.aspect, size: snap.size, customW: snap.customW, customH: snap.customH,
    landscape: snap.landscape, tier: snap.tier, auto: snap.auto,
    steps: snap.steps, cfg: snap.cfg, count: snap.count, varMode: snap.varMode,
    creativity: snap.creativity, highPriority: snap.highPriority, promptHelper: snap.promptHelper,
    boosters: { ...snap.boosters },
    // a restore lands on the LoRA side, the side a snapshot's LoRAs are sent from
    inputs: "loras",
  };
  if (opts && opts.withSeed) p.seed = snap.seed || "";
  return p;
}

/* ---- presets ---------------------------------------------------------------------------- */

/* gen.presets as it comes back: at most 30, unique names, each a valid snapshot. */
export function presetsFromPrefs(v) {
  if (!Array.isArray(v)) return [];
  const out = [];
  const seen = new Set();
  for (const p of v) {
    if (!p || typeof p !== "object") continue;
    const name = typeof p.name === "string" ? p.name.trim().slice(0, PRESET_NAME_MAX) : "";
    if (!name || seen.has(name)) continue;
    const snap = snapshotFrom(p);
    if (!snap) continue;
    delete snap.seed;                       // a preset never carries a seed, whatever was stored
    seen.add(name);
    out.push({ name, ...snap });
    if (out.length >= PRESET_MAX) break;
  }
  return out;
}

/* Save the composer as a preset (page: savePreset): the same name replaces, the newest sits
   first, 30 at most. -> {list} or {error}. */
export function savePreset(list, name, snap) {
  const n = String(name || "").trim().slice(0, PRESET_NAME_MAX);
  if (!n) return { error: "Give the preset a name." };
  const rest = (list || []).filter((p) => p.name !== n);
  if (rest.length >= PRESET_MAX) {
    return { error: "You have " + PRESET_MAX + " presets — delete one to save another." };
  }
  const entry = { name: n, ...snap };
  delete entry.seed;
  const next = [entry, ...rest];
  if (JSON.stringify(next).length > PREF_SOFT_LIMIT) {
    return { error: "Your presets are too large to save one more — delete one first." };
  }
  return { list: next, replaced: rest.length !== (list || []).length };
}

export function deletePreset(list, name) {
  return (list || []).filter((p) => p.name !== name);
}

/* The line under a preset's name (page: p.meta). */
export function presetMeta(p) {
  const n = (p.loras || []).length;
  return [(p.model && p.model.title) || "no model", n + " LoRA" + (n === 1 ? "" : "s"),
    "×" + (p.count || 1) + (p.varMode === "matrix" ? " · matrix" : "")].join(" · ");
}

export function lastNote() { return "Filled from your last send. Nothing was sent."; }
export function presetNote(name) { return "Filled from preset “" + name + "”. Nothing was sent."; }
export const MODEL_GONE = "The model is no longer available, so everything else was filled.";

/* ---- quick picks (NOTES 6) --------------------------------------------------------------- */

const emptyQuick = () => ({ models: { recent: [], fav: [] }, loras: { recent: [], fav: [] }, weights: {} });

const modelEntryFrom = (e) => (e && typeof e === "object" && ID_RE.test(String(e.id || "")) ? {
  id: String(e.id), title: str(e.title, 200), thumb: str(e.thumb, 2048), type: str(e.type, 64),
  hint: FAMILIES.includes(e.hint) ? e.hint : "",
} : null);
const loraEntryFrom = (e) => (e && typeof e === "object" && ID_RE.test(String(e.id || "")) ? {
  id: String(e.id), title: str(e.title, 200), thumb: str(e.thumb, 2048),
  base: str(e.base, 64).toUpperCase(),
} : null);

function listOf(raw, make, max) {
  if (!Array.isArray(raw)) return [];
  const out = [];
  const seen = new Set();
  for (const r of raw) {
    const e = make(r);
    if (!e || seen.has(e.id)) continue;
    seen.add(e.id);
    out.push(e);
    if (out.length >= max) break;
  }
  return out;
}

/* gen.quick as it comes back. */
export function quickFromPrefs(v) {
  const q = emptyQuick();
  if (!v || typeof v !== "object" || Array.isArray(v)) return q;
  const m = v.models || {}, l = v.loras || {};
  q.models.recent = listOf(m.recent, modelEntryFrom, QUICK_RECENT);
  q.models.fav = listOf(m.fav, modelEntryFrom, QUICK_FAV_MAX);
  q.loras.recent = listOf(l.recent, loraEntryFrom, QUICK_RECENT);
  q.loras.fav = listOf(l.fav, loraEntryFrom, QUICK_FAV_MAX);
  if (v.weights && typeof v.weights === "object" && !Array.isArray(v.weights)) {
    for (const k of Object.keys(v.weights)) {
      const w = v.weights[k];
      if (ID_RE.test(k) && typeof w === "number" && isFinite(w) && w >= -10 && w <= 10) q.weights[k] = w;
    }
  }
  return q;
}

export function modelEntryOf(model) {
  return { id: String(model.model_id), title: str(model.title, 200), thumb: str(model.thumb, 2048),
    type: str(model.model_type, 64), hint: FAMILIES.includes(model.base_hint) ? model.base_hint : "" };
}
export function loraEntryOf(l) {
  return { id: String(l.model_id), title: str(l.title, 200), thumb: str(l.preview_url || l.thumb, 2048),
    base: str(l.lora_base_type || l.base, 64).toUpperCase() };
}

/* A picker row (the marketplace's card) as a chip entry. */
export function entryFromRow(kind, row) {
  if (!row || !row.model_id) return null;
  if (kind === "lora") {
    return loraEntryOf({ model_id: row.model_id, title: row.title, preview_url: row.preview_url || row.cover_url,
      lora_base_type: row.lora_base_model_type || row.model_type });
  }
  return modelEntryOf({ model_id: row.model_id, title: row.title, thumb: row.preview_url || row.cover_url,
    model_type: row.model_type || "", base_hint: baseHintOf(row.base_model) });
}

/* A successful send moves the recents: the last 3 DISTINCT models and LoRAs, newest first,
   this send's LoRAs first in their own order (page: fire()), and each LoRA's weight is kept
   as its last-used one. The Context side holds its LoRAs, so it records none. */
export function recordSend(quick, s) {
  const q = quickFromPrefs(quick);
  if (s && s.model && s.model.model_id) {
    const e = modelEntryOf(s.model);
    q.models.recent = [e, ...q.models.recent.filter((x) => x.id !== e.id)].slice(0, QUICK_RECENT);
  }
  const used = s && s.inputs === "context" ? [] : ((s && s.loras) || []).filter((l) => l && l.model_id);
  if (used.length) {
    const es = used.map(loraEntryOf);
    const ids = new Set(es.map((e) => e.id));
    q.loras.recent = [...es.filter((e, i) => es.findIndex((x) => x.id === e.id) === i),
      ...q.loras.recent.filter((x) => !ids.has(x.id))].slice(0, QUICK_RECENT);
    for (const l of used) {
      const w = Number(l.weight);
      if (isFinite(w)) q.weights[String(l.model_id)] = w;
    }
  }
  return pruneWeights(q);
}

/* Weights are kept only for LoRAs still on a chip. */
function pruneWeights(q) {
  const keep = new Set([...q.loras.recent, ...q.loras.fav].map((e) => e.id));
  for (const k of Object.keys(q.weights)) if (!keep.has(k)) delete q.weights[k];
  return q;
}

/* ☆ in a picker: add to (or take out of) the favourites. */
export function toggleFav(quick, kind, entry) {
  const q = quickFromPrefs(quick);
  const bucket = kind === "lora" ? q.loras : q.models;
  const at = bucket.fav.findIndex((x) => x.id === entry.id);
  if (at >= 0) bucket.fav.splice(at, 1);
  else bucket.fav = [entry, ...bucket.fav].slice(0, QUICK_FAV_MAX);
  return pruneWeights(q);
}

export function isFav(quick, kind, id) {
  const q = quickFromPrefs(quick);
  return (kind === "lora" ? q.loras : q.models).fav.some((x) => x.id === String(id));
}

export function favIds(quick, kind) {
  const q = quickFromPrefs(quick);
  return (kind === "lora" ? q.loras : q.models).fav.map((x) => x.id);
}

/* The chips of one row: the 3 recents, then the favourites that are not among them, at most 6
   (page M4). `on` = in the composer now; a LoRA for another family is `dim`, with its reason in
   the title. -> [{id, label, title, on, dim, fav}] */
export function quickChips(quick, kind, s) {
  const q = quickFromPrefs(quick);
  const bucket = kind === "lora" ? q.loras : q.models;
  const favSet = new Set(bucket.fav.map((x) => x.id));
  const seen = new Set();
  const entries = [...bucket.recent, ...bucket.fav].filter((e) => (seen.has(e.id) ? false : (seen.add(e.id), true)));
  const chips = entries.slice(0, QUICK_ROW_MAX).map((e) => {
    const fav = favSet.has(e.id);
    if (kind === "lora") {
      const on = ((s && s.loras) || []).some((l) => String(l.model_id) === e.id);
      const w = q.weights[e.id];
      const mType = String(s && s.model && s.model.model_type || "").toUpperCase();
      const dim = !!(e.base && mType && e.base !== mType);
      return {
        id: e.id, entry: e, on, dim, fav,
        label: (fav ? "★ " : "") + e.title + " " + (w != null ? w : 0.7),
        title: dim ? "For " + (archName(e.base) || e.base) + " models; " + ((s.model && s.model.title) || "this model")
          + " is " + (archName(mType) || mType)
          : on ? "Tap to remove" : "Tap to add at its last weight",
      };
    }
    const on = !!(s && s.model && String(s.model.model_id) === e.id);
    return { id: e.id, entry: e, on, dim: false, fav,
      label: (fav ? "★ " : "") + e.title,
      title: (archName(e.type) || e.hint || "Model") + " · " + (on ? "in use" : "tap to switch") };
  });
  return chips;
}

/* The weight a LoRA chip adds at. */
export function chipWeight(quick, id) {
  const w = quickFromPrefs(quick).weights[String(id)];
  return w != null ? w : 0.7;
}

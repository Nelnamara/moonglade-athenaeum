/* The model and LoRA pickers' Saved tab (Session S, Saved Tab Handoff, drift 134-139) -- the
   logic, importless on purpose so loom/test/mg-model-picker-saved.test.js pins it without a
   renderer, a DOM or a fetch. ModelPicker.jsx and picker/SavedTab.jsx draw it.

   WHAT SAVED IS. PixAI keeps one reserved default model collection per account, which its own
   Save button writes and which it shows as "Saved"; models and LoRAs share it. Named
   collections are "sets", the word recipes already use (❖ Collections keeps its own word).
   The tab reads it live -- moonglade_recipes.model_sets / model_page through
   /api/model-saved/sets and /api/model-search?src=saved -- and nothing writes when it opens. */

/* Below this picker width the 112 px rail folds into a "Saved ▾" chooser (S1c). */
export const NARROW_PX = 640;

/* The LoRA picker's base chips: one `loraBaseModelTypes` value each, every one of them a value
   the 2026-10-03 probe saw the collection accept. Same labels and order as Market's model-type
   chips (ModelPicker's BASE_TYPES), less the Community DiT pair: the filter takes ONE value. */
export const SAVED_BASES = [
  ["", "All"], ["MMDIT26B_MODEL", "DiT.3"], ["MMDIT26A_MODEL", "DiT.2"], ["DIT7_MODEL", "DiT.1"],
  ["SDXL_MODEL", "SDXL"], ["SD_V1_MODEL", "SD 1.5"],
];

export const SAVED_END_LINE = "That's everything";

function fmt(n) { return (Number(n) || 0).toLocaleString("en-US"); }

/* The header's count, "N · M old · K not available", as clauses: each one is left out at zero
   (S5c). N is PixAI's own count for this picker's kind, M the old bookmarks merged in, K the
   saved models PixAI no longer has. The caller joins them with " · " and makes K the button
   that opens the list of them. */
export function countClauses({ count = 0, old = 0, gone = 0 } = {}) {
  const out = [];
  if (Number(count) > 0) out.push({ key: "count", text: fmt(count) });
  if (Number(old) > 0) out.push({ key: "old", text: fmt(old) + " old" });
  if (Number(gone) > 0) out.push({ key: "gone", text: fmt(gone) + " not available" });
  return out;
}

/* Empty is one line pointing at Market; a keyword that matches nothing says so instead. */
export function savedEmptyLine(kind, q) {
  const many = kind === "lora" ? "LoRAs" : "models";
  if (q) return "No saved " + many + " match “" + q + "”.";
  return "Nothing saved for " + many + " yet. Use ⊕ Save on any " + (kind === "lora" ? "LoRA" : "model")
    + " in Market.";
}

/* A failed read is peach with Retry and is never drawn as empty. */
export function savedErrorLine(title) {
  return "Couldn't load " + (title || "Saved") + ".";
}

/* The source row's label for Saved: the chooser's ▾ shows only where the rail is folded. */
export function savedTabLabel(wide) {
  return wide ? "Saved" : "Saved ▾";
}

/* The set on screen: `setId` "" means Saved, the reserved default. */
export function currentSet(sets, setId) {
  const list = sets || [];
  return list.find((s) => s.id === setId) || list.find((s) => s.reserved) || null;
}

/* A removed model's line in "K not available ▸": nothing says which model it was, only when
   it was saved. */
export function goneLine(item) {
  const d = String((item && item.saved_at) || "").slice(0, 10);
  return "Removed from PixAI" + (d ? " · saved " + d : "");
}

/* ---- S2c: the old bookmarks ---- */

/* The per-account switch behind "Show old bookmarks" (hooks/useAccountPrefs.js). Absent = on. */
export const OLD_PREF = "picker.old_bookmarks";

/* The old bookmarks list has taken no save since mid-August. Saved shows the ones it does not
   hold (the server already left out every one Saved holds; `live` covers what this session
   saved since), after its own rows, in the old list's order, each tagged `old`. The search
   box and the LoRA base chip narrow them as they narrow the live list. */
export function mergeOld(live, old, { q = "", base = "" } = {}) {
  const held = new Set((live || []).map((r) => String(r.model_id)));
  const words = String(q || "").toLowerCase().split(/\s+/).filter(Boolean);
  return (old || []).filter((r) => {
    if (held.has(String(r.model_id))) return false;
    if (base && r.lora_base_model_type !== base) return false;
    const hay = ((r.title || "") + " " + (r.description || "")).toLowerCase();
    return words.every((w) => hay.includes(w));
  }).map((r) => (r.old ? r : { ...r, old: true }));
}

/* ---- S3b + S4c: saving, and the "Keep this model" menu ---- */

export const SAVED_NOTE = "Saved · read back from PixAI.";
export const READ_ONLY_LINE = "Read-only mode is on, so saving to PixAI is off.";

export function keepTitle(kind) {
  return kind === "lora" ? "Keep this LoRA" : "Keep this model";
}

/* An answer that never reached the page (api.js's transport failure). The write may have
   landed, so it is read back -- never sent again. */
export function isTransportError(d) {
  return !!(d && typeof d.error === "string" && /^network error/i.test(d.error));
}

/* How a write's answer becomes a card. The server's answer carries what its read-back found
   (`contains`); that decides. `contains` null or absent means nothing is known: the card keeps
   what it showed and the words say why. `ok` is "PixAI now says what was asked for". */
export function afterWrite(prev, d, want) {
  const p = prev || { saved: false, item_id: "" };
  if (d && typeof d.contains === "boolean") {
    return { saved: d.contains, item_id: d.contains ? String(d.item_id || "") : "",
             error: d.error || "", ok: d.contains === want && !d.error };
  }
  return { saved: !!p.saved, item_id: p.item_id || "", error: (d && d.error) || "PixAI didn't answer",
           ok: false };
}

/* What the page knows about each model's place in Saved: model id -> {saved, item_id}. Filled
   by Saved's own rows, the menu's reads and every write's read-back; every card reads it. */
export function createSavedStore() {
  const state = new Map();
  const subs = new Set();
  let ver = 0;
  const publish = () => { ver += 1; subs.forEach((f) => f()); };
  return {
    get: (id) => state.get(String(id)),
    set: (id, v) => { state.set(String(id), v); publish(); },
    setMany: (entries) => { for (const [id, v] of entries) state.set(String(id), v); publish(); },
    subscribe: (f) => { subs.add(f); return () => { subs.delete(f); }; },
    version: () => ver,
  };
}

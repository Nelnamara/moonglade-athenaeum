/* Train a LoRA — the two small rules both train panels (TrainOverlay, TrainMobile) share with
   the server (SCOPE_2026-09-26 E7). Pure, so loom/test/train-core.test.js can hold them. */

/* PixAI's own trigger-word normalizer, in its order (the train page's he()): runs of CR/LF
   become ", ", any whitespace run one space, a run of commas with spaces between them one
   ", ", lowercase, then leading and trailing commas and whitespace stripped. The server's
   core.normalize_trigger_words is the same five steps, and its 256 / 30 limits are measured on
   this string's `length` (UTF-16 code units, as the site measures it) -- so the panel's counter
   shows normalizeTrigger(text).length, the number the server will actually check. */
export function normalizeTrigger(text) {
  return String(text ?? "")
    .replace(/[\r\n]+/g, ", ")
    .replace(/\s+/g, " ")
    .replace(/,\s*(?:,\s*)+/g, ", ")
    .toLowerCase()
    .replace(/^[,\s]+|[,\s]+$/g, "");
}

/* The confirm's `accept_credit_cost`: nothing for a run the preview called free; otherwise the
   AMOUNT the ticked box named (`true` only when the preview could not quote one). The server
   refuses a number that is no longer the run's price (409), so an acknowledgement is always for
   the price the user read -- never for a base picked after the quote. */
export function acceptCostField(ask, accepted) {
  if (!ask || ask.is_free) return {};
  if (!accepted) return { accept_credit_cost: false };
  return { accept_credit_cost: typeof ask.price === "number" ? ask.price : true };
}

/* ---------------------------------------------------------------------------------------------
   Session J (Training Handoff, 2026-09-28) -- the rules the desktop overlay and the phone screen
   share. Pure: loom/test/train-core.test.js holds them. The server re-checks every one that
   touches money or the account; these decide only what the panels draw and enable. */

export const MIN_IMAGES = 10;
export const MAX_IMAGES = 100;
export const CAPTION_MAX = 1000;
// Basic's four goals and Advanced's categories: PixAI's own values (its "Something else"
// sub-kind is never sent).
export const GOALS = Object.freeze([
  { value: "character", label: "Character", desc: "One specific person or character" },
  { value: "style", label: "Art style", desc: "One set of linework and colours" },
  { value: "clothing", label: "Outfit", desc: "One outfit, on any character" },
  { value: "other", label: "Something else", desc: "Animals, poses, backgrounds and more" },
]);
// A tile's source mark (handoff 2a): upload, from history, an imported set.
export const SOURCE_MARK = Object.freeze({ upload: "⬆", history: "▦", dataset: "⎘" });

/* Add images to the one grid, de-duplicated by media id, never past 100. `incoming` is
   [{media_id, thumb?}]; each keeps the first source it arrived by. Returns the new list and
   how many were added / already there / left out for room. */
export function mergeImages(current, incoming, source) {
  const out = (current || []).slice();
  const seen = new Set(out.map((x) => x.media_id));
  let counted = countedItems(out).length;
  let added = 0, dup = 0, full = 0;
  for (const it of incoming || []) {
    const id = it && String(it.media_id || "");
    if (!id) continue;
    if (seen.has(id)) { dup += 1; continue; }
    if (counted >= MAX_IMAGES) { full += 1; continue; }
    seen.add(id);
    out.push({ media_id: id, source: it.source || source, thumb: it.thumb || "" });
    counted += 1;
    added += 1;
  }
  return { items: out, added, dup, full };
}

/* The images that count (handoff 2a: "Rejected files show with a peach reason and aren't
   counted"). A tile PixAI's image rule refused carries `reject` (the server's reason) and stays
   in the grid, peach, until it is taken out; it is never sent and never counts toward 10-100. */
export function countedItems(items) {
  return (items || []).filter((x) => !x.reject);
}

/* Mark the tiles the server's image rule refused (the Basic preview's `rejected_images`,
   [{media_id, why}]). Returns a new list; a tile not named keeps its state. */
export function markRejected(items, rejected) {
  const why = new Map((rejected || []).map((r) => [String(r.media_id), String(r.why || "refused")]));
  if (!why.size) return items || [];
  return (items || []).map((x) => (why.has(x.media_id) ? { ...x, reject: why.get(x.media_id) } : x));
}

export function roomLeft(items) {
  return Math.max(0, MAX_IMAGES - countedItems(items).length);
}

/* An earlier set that won't fit what's left of 100 is dimmed (handoff 2a). Counts only the
   images not already in the grid. */
export function datasetFits(dataset, items) {
  const have = new Set((items || []).map((x) => x.media_id));
  const extra = (dataset.media_ids || []).filter((m) => !have.has(String(m))).length;
  return extra <= roomLeft(items);
}

/* A REUSE (PixAI's lower reuse price) is exactly one earlier set, whole: every image in the
   grid came from that set and the grid holds all of it, nothing added or removed -- the
   site's own check. Returns that set's task id, or "". The server checks it again. */
export function reuseCandidate(items, datasets) {
  const list = countedItems(items);
  if (!list.length || list.some((x) => x.source !== "dataset")) return "";
  const ids = new Set(list.map((x) => x.media_id));
  for (const d of datasets || []) {
    const ds = (d.media_ids || []).map(String);
    if (ds.length === list.length && ds.every((m) => ids.has(m))) return String(d.task_id);
  }
  return "";
}

/* PixAI's image rule on a picture's own size (an upload is checked before it leaves): each
   side at least 512, the long side no more than 3 x the short. null when it passes. */
export function imageProblem(w, h, rule) {
  const r = rule || {};
  const minW = Number(r.minWidth) || 512, minH = Number(r.minHeight) || 512;
  const ar = Number(r.maxAspectRatio) || 3;
  if (!(w > 0 && h > 0)) return "its size couldn't be read";
  if (w < minW || h < minH) return "smaller than " + minW + "×" + minH;
  if (Math.max(w, h) / Math.min(w, h) > ar) return "longer than " + ar + ":1";
  return null;
}

/* The trigger rule as the panels state it: counted on the tidied string (normalizeTrigger),
   up to 256, at least 30 on a DiT.2 / DiT.3 base. `problem` is the peach line's reason, or
   "" when it is fine. `spacing` notes the raw text's double or edge spaces (PixAI's own
   wording; the tidy removes them before sending). */
export function triggerCheck(raw, needsLong) {
  const t = normalizeTrigger(raw);
  const n = t.length;
  let problem = "";
  if (!n) problem = "required";
  else if (n > 256) problem = "too long: 256 characters at most";
  else if (needsLong && n < 30) problem = "needs at least 30 characters on this base";
  const s = String(raw || "");
  const spacing = /\s{2,}/.test(s.trim()) || (s.length > 0 && /^\s|\s$/.test(s));
  return { text: t, length: n, problem, ok: !problem, spacing };
}

export const LONG_TRIGGER_ARCHS = Object.freeze(["MMDIT26A_MODEL", "MMDIT26B_MODEL"]);

export function etaText(eta) {
  if (!eta || !(eta.min > 0)) return "";
  return "about " + eta.min + "–" + eta.max + " minutes";
}

export function etaLeftText(ms) {
  if (!(ms > 0)) return "";
  const m = Math.max(1, Math.round(ms / 60000));
  return m >= 90 ? "~" + Math.round(m / 60) + " h" : "~" + m + " min";
}

export function credits(n) {
  return typeof n === "number" && Number.isFinite(n) ? n.toLocaleString("en-US") : "";
}

/* The Runs pill and the one action a row offers (handoff 5c): Draft peach, named by its step;
   Queued / Training lavender; Done emerald; Failed ruby. Published rows show their visibility
   and offer Use. A failure already retried (the server's on-disk guard) offers nothing. */
export function runStatus(row) {
  const r = row || {};
  const st = r.status;
  if (st === "draft" || st === "captionReady") {
    const step = r.step === "images" ? "images" : "descriptions";
    return { label: "Draft · " + step, tone: "peach", action: "continue", actionLabel: "Continue" };
  }
  if (st === "captioning") {
    return { label: "Draft · describing", tone: "peach", action: "continue", actionLabel: "Continue" };
  }
  if (st === "waiting") return { label: "Queued", tone: "lavender", action: "view", actionLabel: "View" };
  if (st === "running") {
    const p = typeof r.progress === "number" ? Math.floor(r.progress) + "%" : "";
    return { label: "Training" + (p ? " · " + p : ""), tone: "lavender", action: "view", actionLabel: "View" };
  }
  if (st === "failed") {
    const g = r.retry && r.retry.state;
    const canRetry = r.mode === "advanced" && !g;
    const label = g === "done" ? "Failed · retried"
      : g ? "Failed · a retry may have started" : "Failed";
    return { label, tone: "ruby", action: canRetry ? "retry" : null, actionLabel: canRetry ? "Retry" : "" };
  }
  if (st === "done") {
    if (r.published || r.model_id) {
      const vis = r.visibility === "public" ? "Public" + (r.rebate ? " · rebates" : "")
        : r.visibility === "private" ? "Private" : "Done";
      return { label: vis, tone: "emerald", action: "use", actionLabel: "Use" };
    }
    return { label: "Done", tone: "emerald", action: "publish", actionLabel: "Publish" };
  }
  return { label: st || "…", tone: "muted", action: null, actionLabel: "" };
}

export const RUN_FILTERS = Object.freeze([
  { key: "all", label: "All" },
  { key: "draft", label: "Drafts" },
  { key: "done", label: "Done" },
  { key: "failed", label: "Failed" },
]);

export function runMatches(row, key) {
  if (!key || key === "all") return true;
  if (key === "draft") return ["draft", "captioning", "captionReady"].includes(row.status);
  return row.status === key;
}

/* The chooser's Runs row (handoff 1a: "… · 1 training · 1 draft"): what is live and what waits
   for the owner, counted off the runs list. Zero counts are left out; "" when nothing is. */
export function runsSummary(runs) {
  const rows = runs || [];
  const n = (pred) => rows.filter(pred).length;
  const parts = [];
  const training = n((r) => r.status === "running" || r.status === "waiting");
  const drafts = n((r) => runMatches(r, "draft"));
  const publish = n((r) => runStatus(r).action === "publish");
  const failed = n((r) => r.status === "failed");
  if (training) parts.push(training + " training");
  if (drafts) parts.push(drafts + (drafts === 1 ? " draft" : " drafts"));
  if (publish) parts.push(publish + " to publish");
  if (failed) parts.push(failed + " failed");
  return parts.join(" · ");
}

/* "Use" (handoff 5c): a trained LoRA as the Generate dock's addLora takes it. null when the
   row has no LoRA yet. `archOf(versionId)` names the base's architecture. */
export function loraForDock(row, archOf) {
  if (!row || !row.model_id) return null;
  return {
    model_id: String(row.model_id), version_id: String(row.version_id || ""),
    title: row.title || "", preview_url: row.cover || "", weight: 0.7,
    trigger_words: row.trigger_words || "",
    lora_base_model_type: (archOf && archOf(row.base_version_id)) || "",
  };
}

/* The one confirm's button (handoff 2a; BUILD 7): it names the QUOTED amount the confirm will
   send -- the preview's own `price`, never the config's -- or says the run is free. */
export function startLabel(ask, verb = "Start training") {
  if (!ask) return verb;
  if (ask.is_free) return verb + " · free";
  return typeof ask.price === "number" ? verb + " · " + credits(ask.price) : verb;
}

/* The publish sheet's consequence ticks (handoff 4a): private has one, public adds the second.
   Switching visibility clears them. The server requires exactly these keys. */
export function publishTicks(visibility) {
  const t = [{ key: "no_delete", text: "I can no longer delete this LoRA (it can only be hidden)" }];
  if (visibility === "public") t.push({ key: "no_private", text: "It can't go back to private" });
  return t;
}

/* PixAI's description filters (its step 2): All · Auto · Edited · Not described yet. An image
   is "edited" when the owner's text differs from the machine's. */
export function captionState(mid, captions) {
  const c = (captions || {})[mid];
  if (!c) return "none";
  if (c.source === "user" && c.text !== c.machine_text) return "edited";
  return "auto";
}

export function captionCounts(ids, captions) {
  const n = { all: 0, auto: 0, edited: 0, none: 0 };
  for (const m of ids || []) {
    n.all += 1;
    n[captionState(m, captions)] += 1;
  }
  return n;
}

/* The grid's tools, applied to one description: find/replace (every occurrence, literal), and
   a tag added or removed as a comma-separated item. Each answers the new text, or null when it
   would change nothing, empty it, or pass the 1,000-character cap. */
export function replaceIn(text, find, repl) {
  const t = String(text || "");
  if (!find || !t.includes(find)) return null;
  const out = t.split(find).join(String(repl || "")).replace(/\s{2,}/g, " ").trim();
  return out && out !== t && out.length <= CAPTION_MAX ? out : null;
}

function tagList(text) {
  return String(text || "").split(",").map((s) => s.trim()).filter(Boolean);
}

export function addTag(text, tag) {
  const tg = String(tag || "").trim();
  if (!tg) return null;
  const tags = tagList(text);
  if (tags.some((x) => x.toLowerCase() === tg.toLowerCase())) return null;
  const out = tags.concat([tg]).join(", ");
  return out.length <= CAPTION_MAX ? out : null;
}

export function removeTag(text, tag) {
  const tg = String(tag || "").trim().toLowerCase();
  if (!tg) return null;
  const tags = tagList(text);
  const kept = tags.filter((x) => x.toLowerCase() !== tg);
  return kept.length !== tags.length && kept.length ? kept.join(", ") : null;
}

/* The base picker's tabs (handoff 6a): each architecture, the Recommended one first and
   labelled, in the server's order otherwise. */
export function archTabs(groups) {
  const gs = (groups || []).slice();
  gs.sort((a, b) => (b.recommended ? 1 : 0) - (a.recommended ? 1 : 0));
  return gs.map((g) => ({ arch: g.arch, label: g.label, recommended: !!g.recommended,
    models: g.models || [], price: g.price, reuse: g.reuse, listPrice: g.list_price }));
}

/* The base the panel pre-selects: the server's default_version_id and the tab that holds it
   (Session J 6a: Tsubaki.3, Recommended). */
export function defaultBase(groups, versionId) {
  const tabs = archTabs(groups);
  const gi = tabs.findIndex((g) => g.models.some((m) => m.version_id === versionId));
  if (gi >= 0) return { tab: gi, base: versionId };
  return { tab: 0, base: tabs[0] && tabs[0].models[0] ? tabs[0].models[0].version_id : "" };
}

/* What the Basic footer shows before Start (handoff 2a, "the price, the free badge / struck
   list price"): the member's free trainings zero it with the list price struck; otherwise the
   price at the right tier (reuse when a whole earlier set is reused, named). A card is only
   known at Start's check, so it is never promised here. */
export function basicFooterCost({ quota, tab, reuse }) {
  const t = tab || {};
  const list = typeof t.price === "number" ? t.price : null;
  const price = reuse && typeof t.reuse === "number" ? t.reuse : list;
  if (quota > 0) return { free: true, price: 0, struck: price, badge: quota + (quota === 1 ? " time free" : " times free"), reason: reuse ? "reusing a dataset" : "" };
  return { free: false, price, struck: null, badge: "", reason: reuse ? "reusing a dataset" : "" };
}

/* ---------------------------------------------------------------------------------------------
   Advanced (Training Handoff C / decision 3c, with the owner's 2026-09-28 corrections in
   BUILD-w3-train.md section 5): the rules both Advanced screens (desktop TrainAdvanced, the
   phone's Advanced steps) share. Pure; loom/test/train-core.test.js holds them. */

/* PixAI's own defaults, the ones its advanced page locks and submits (and the server sends
   verbatim: core.TRAIN_DEFAULT_OPTIONS). The contract's ranges are drawn on the locked tracks
   so the page reads as the handoff draws it. */
export const ADVANCED_DEFAULTS = Object.freeze({ steps: 325, learningRate: 0.0006, rank: 64, gradAccum: 2 });
export const STEP_RANGE = Object.freeze({ min: 50, max: 800 });
export const LR_RANGE = Object.freeze({ min: 0.00005, max: 0.001 });
export const RANKS = Object.freeze([8, 16, 32, 64]);

/* PixAI's own estimate (its advanced page): t = max(1, round(steps × 27/325)) minutes, shown as
   "about t–round(t × 1.3) minutes". The same numbers the server's core.training_eta answers. */
export function etaForSteps(steps) {
  const s = Number(steps);
  const t = Math.max(1, Math.round((Number.isFinite(s) ? s : ADVANCED_DEFAULTS.steps) * 27 / 325));
  return { min: t, max: Math.round(t * 1.3) };
}

/* Where a value sits on its drawn track, 0-100 (the locked tracks' fill). */
export function trackPercent(value, range) {
  const v = Number(value), lo = Number(range && range.min), hi = Number(range && range.max);
  if (!Number.isFinite(v) || !(hi > lo)) return 0;
  return Math.round(Math.min(1, Math.max(0, (v - lo) / (hi - lo))) * 100);
}

/* Advanced's set-up line under the trigger box (handoff C1, peach inline): the tidied count out
   of 256 and what is wrong, PixAI's spacing rule named. `warn` colours it peach; `block` is what
   keeps "Next · creates a draft" off (the spacing is tidied before sending, so it warns only). */
export function advancedTriggerLine(raw) {
  const c = triggerCheck(raw, true);
  const rules = "No double spaces, and no space at the start or end.";
  if (!String(raw || "").length) {
    return { text: "At least 30 characters, up to 256. " + rules, warn: false, block: true };
  }
  if (!c.ok) return { text: c.length + " / 256: " + c.problem + ". " + rules, warn: true, block: true };
  if (c.spacing) {
    return { text: c.length + " / 256: " + rules + " They're taken out before it's sent.", warn: true, block: false };
  }
  return { text: c.length + " / 256", warn: false, block: false };
}

/* PixAI's description filters (its step 2), in its order. */
export const CAPTION_FILTERS = Object.freeze([
  { key: "all", label: "All" },
  { key: "auto", label: "Auto" },
  { key: "edited", label: "Edited" },
  { key: "none", label: "Not described yet" },
]);

export function captionFilter(ids, captions, key) {
  if (!key || key === "all") return (ids || []).slice();
  return (ids || []).filter((m) => captionState(m, captions) === key);
}

/* What the Descriptions step lets the owner press (BUILD 5 + spend review finding 9):
   - describe: PixAI describes first, and only on its own quote (`quote` = the route's
     {image_count, total_price}); never with fewer than 10 images, while it is already
     describing, with nothing left to describe, without a quote, or while a save is pending.
   - next ("Next: parameters"): only once every image in the set is described, 10 or more,
     nothing pending and nothing describing.
   Each gate answers why it is off, in words the screen can show. */
export function advancedGates({ mediaIds, captions, quote, saving, status, busy }) {
  const ids = mediaIds || [];
  const caps = captions || {};
  const left = ids.filter((m) => !caps[m]).length;
  const pending = (saving || 0) > 0;
  let describe = "";
  if (ids.length < MIN_IMAGES) describe = "Add at least " + (MIN_IMAGES - ids.length) + " more image" + (MIN_IMAGES - ids.length === 1 ? "" : "s") + " first.";
  else if (status === "captioning") describe = "PixAI is describing them now.";
  else if (!left) describe = "Every image is described.";
  else if (!quote || typeof quote.total_price !== "number") describe = "PixAI's price for describing couldn't be read; try again in a moment.";
  else if (!(quote.image_count > 0)) describe = "Nothing left to describe.";
  else if (pending) describe = "Saving your edits first.";
  else if (busy) describe = "Working…";
  let next = "";
  if (ids.length < MIN_IMAGES) next = "At least " + MIN_IMAGES + " images.";
  else if (status === "captioning") next = "Wait until PixAI has described them.";
  else if (left) next = left + " image" + (left === 1 ? " isn't" : "s aren't") + " described yet.";
  else if (pending) next = "Saving your edits first.";
  else if (busy) next = "Working…";
  return { describe: !describe, whyNoDescribe: describe, next: !next, whyNoNext: next, left };
}

/* The describe button (BUILD 5: "Describe automatically (N images)" with PixAI's own quote --
   the count and the total come ONLY from the quote, never from the set's size or the config). */
export function describeLabel(quote) {
  if (!quote || !(quote.image_count > 0) || typeof quote.total_price !== "number") return "Describe automatically";
  return "Describe automatically (" + quote.image_count + " image" + (quote.image_count === 1 ? "" : "s") + ") · " + credits(quote.total_price);
}

/* The per-image line under the describe question: PixAI's unit price, read off its own quote. */
export function perImage(quote) {
  if (!quote || !(quote.image_count > 0) || typeof quote.total_price !== "number") return null;
  return Math.round(quote.total_price / quote.image_count);
}

/* The focus view's move (← → J K, the strip, a swipe): clamped to the set, never wrapping. */
export function stepFocus(i, n, delta) {
  if (!(n > 0)) return 0;
  return Math.min(n - 1, Math.max(0, (Number(i) || 0) + delta));
}

/* The strip under the focus view: `count` thumbnails around the current one, clamped. */
export function focusWindow(i, n, count = 10) {
  if (!(n > 0)) return [];
  const k = Math.min(count, n);
  const start = Math.max(0, Math.min(n - k, i - Math.floor(k / 2) + 1));
  return Array.from({ length: k }, (_, j) => start + j);
}

/* A clause as its own sentence: capitalised, one full stop ("about 27–35 minutes" ->
   "About 27–35 minutes."). "" stays "". */
export function sentence(text) {
  const t = String(text || "").trim();
  if (!t) return "";
  return t.charAt(0).toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? "" : ".");
}

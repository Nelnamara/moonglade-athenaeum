/* THE FOLIO FOR COMPLETIONISTS -- the pure logic (Session O, O1-O3, and Small Calls L2's relic
   rows). Nothing here touches React, the DOM or the network, so loom/test/folio-completionist-core
   .test.js holds every rule.

   ONE RULE GOVERNS THE FILE: FEATS LEAK NOTHING (Session G). A feat is never counted in a
   total, never given an "N to go", never sorted, never pinned; it is shown only as "N found",
   and only once earned. Every function below that walks the achievements starts by setting
   feats aside (isFeatLike), so a caller that forgets to filter still cannot leak one. The
   server sends unearned hidden feats nowhere in the array, so what is set aside here is the
   feats the account has already found plus any feat-tier entry that is not hidden. */

import { fractionOf } from "../lib/moonGaugeCore.js";

/* A feat of ANY kind: the feat tier, the feat bucket, and the meta bucket (the Glories, which
   the Folio folds into Feats). The server holds the same line in achievement_progress(). */
export function isFeatLike(a) {
  return !!a && (a.tier === "feat" || a.bucket === "feat" || a.bucket === "meta");
}

/* ---- O1: "N to go" -------------------------------------------------------------------- */

/* Where a metric's "→" jump goes. Keyed on the metric NAMES this app's server measures (the
   handoff draws four stand-ins: images, shots, entries, likes); each row says which surface
   advances the count. A metric with no entry has no jump -- it still shows its count and moon.
   The four surfaces are the app's own: Generate (the dock), The Loom, Contests, Publish. */
export const JUMPS = Object.freeze({
  images: "generate", videos: "generate", local_gens: "generate", gens_in_a_day: "generate",
  storyboards: "loom", shots: "loom",
  contest_entries: "contests", contest_wins: "contests", entries: "contests",
  published: "publish", likes: "publish",
});
export const JUMP_LABELS = Object.freeze({
  generate: "Generate", loom: "The Loom", contests: "Contests", publish: "Publish",
});

/* The surface key for a metric, or "" when it has none. */
export function jumpFor(metric) {
  return typeof metric === "string" && Object.prototype.hasOwnProperty.call(JUMPS, metric)
    ? JUMPS[metric] : "";
}

/* The count for ONE honor, from the server's own `progress` block, or null. Null means: no
   count, no moon, no pin. It is null for a feat of any kind, for an honor already earned, and
   for one the server did not send progress for (an unmeasured metric), and for numbers that
   are not a real count. `left` is recomputed here from the two numbers rather than trusted,
   and the fraction comes from the moon gauge's own fractionOf, so the moon is only ever drawn
   for a true fraction. */
export function progressOf(a) {
  if (!a || a.earned || isFeatLike(a)) return null;
  const p = a.progress;
  if (!p || typeof p !== "object") return null;
  const current = Number(p.current), threshold = Number(p.threshold);
  if (!Number.isFinite(current) || !Number.isFinite(threshold) || threshold <= 0 || current < 0) return null;
  const fraction = fractionOf(current, threshold);
  if (fraction === null) return null;
  return { current, threshold, left: Math.max(0, threshold - current), fraction };
}

const nfmt = (n) => Number(n).toLocaleString();

/* "12 to go" (never "0 to go": an honor about to be earned reads "nearly there"; the count
   only says something while there is something to count). */
export function toGoText(p) {
  if (!p) return "";
  return p.left > 0 ? nfmt(p.left) + " to go" : "nearly there";
}

/* The jump for one honor: {to, label} or null. Only an honor that HAS a count gets one (an
   unmeasured metric has no way forward to point at, and a feat is never pointed at). */
export function jumpOf(a) {
  if (!progressOf(a)) return null;
  const to = jumpFor(a.metric);
  return to ? { to, label: JUMP_LABELS[to] } : null;
}

/* ---- O2: the completion meter --------------------------------------------------------- */

/* Ladders + milestones + masteries only (the streaks fold into masteries, as the Folio's own
   buckets do). `found` is the feats the account has earned -- shown as "N found" and NEVER part
   of `total` or `pct`, so finding a feat never moves the meter. `pct` is floored, so 100 means
   everything in the pool is earned and nothing rounds up to it. */
export function completionOf(achievements) {
  const list = Array.isArray(achievements) ? achievements : [];
  const pool = list.filter((a) => !isFeatLike(a));
  const earned = pool.filter((a) => a.earned).length;
  const total = pool.length;
  return {
    earned, total,
    pct: total > 0 ? Math.floor((earned * 100) / total) : 0,
    found: list.filter((a) => isFeatLike(a) && a.earned).length,
  };
}

/* The line under the meter: "31 of 143 ladders · milestones · masteries   ·   Feats: 3 found".
   The feats half is left off until one has been found (the Feats stay cloaked until then). */
export function meterLine(c) {
  const base = nfmt(c.earned) + " of " + nfmt(c.total) + " ladders · milestones · masteries";
  return c.found > 0 ? base + "   ·   Feats: " + nfmt(c.found) + " found" : base;
}

/* ---- O3: the sort --------------------------------------------------------------------- */

export const SORT_KEY = "mg_folio_sort";
export const SORTS = Object.freeze([
  { key: "default", label: "Default", note: "bucket order" },
  { key: "closest", label: "Closest to earning", note: "unearned by fraction done, then earned" },
  { key: "rarest", label: "Rarest", note: "by rarity rank" },
  { key: "newest", label: "Newest earned", note: "most recently earned first" },
]);
export const DEFAULT_SORT = "default";

/* A stored value -> a sort key; anything unknown (a stale value, a hand-edited one) is the
   default. */
export function readSort(raw) {
  return SORTS.some((s) => s.key === raw) ? raw : DEFAULT_SORT;
}

/* Remembered per DEVICE: this browser's own storage, never the account. Every read and write
   is guarded, because storage can be blocked or absent, and the Folio must render either way. */
export function loadSort(storage) {
  try { return readSort(storage && storage.getItem(SORT_KEY)); } catch { return DEFAULT_SORT; }
}
export function saveSort(storage, key) {
  try { if (storage) storage.setItem(SORT_KEY, readSort(key)); return true; } catch { return false; }
}

export function sortNote(key) {
  const s = SORTS.find((x) => x.key === key);
  return s ? s.note : SORTS[0].note;
}

const RARITY_RANK = { common: 0, rare: 1, epic: 2, legendary: 3 };
const rankOf = (a) => (Object.prototype.hasOwnProperty.call(RARITY_RANK, a.tier) ? RARITY_RANK[a.tier] : -1);

/* The honors in the chosen order. `items` arrives in the Folio's default order (the ladders in
   their tracks, then the milestones, then the masteries); the default returns it as it is.
   Every sort is STABLE against that order, and every sort sets feats aside first, so a feat
   can never appear in a sorted list at all.

     closest  unearned with a known count by fraction done, more points first among equals; then
              unearned whose count is not known; then everything earned
     rarest   by rarity rank, legendary first
     newest   earned ones by the day they were earned, newest first (an earned honor with no
              recorded day follows the dated ones); then everything unearned

   `earnedAt` is the payload's {id: "YYYY-MM-DD"}. */
export function sortHonors(items, key, earnedAt) {
  const base = (Array.isArray(items) ? items : []).filter((a) => !isFeatLike(a));
  const sort = readSort(key);
  if (sort === "default") return base;
  const at = earnedAt || {};
  const idx = new Map(base.map((a, i) => [a.id, i]));
  const byOrder = (x, y) => idx.get(x.id) - idx.get(y.id);
  const out = base.slice();
  if (sort === "rarest") {
    return out.sort((x, y) => (rankOf(y) - rankOf(x)) || byOrder(x, y));
  }
  if (sort === "newest") {
    const day = (a) => (a.earned && typeof at[a.id] === "string" ? at[a.id] : "");
    return out.sort((x, y) => {
      if (x.earned !== y.earned) return x.earned ? -1 : 1;
      if (!x.earned) return byOrder(x, y);
      const dx = day(x), dy = day(y);
      if (dx !== dy) return dx === "" ? 1 : dy === "" ? -1 : (dx < dy ? 1 : -1);
      return byOrder(x, y);
    });
  }
  // closest
  const frac = (a) => { const p = progressOf(a); return p ? p.fraction : null; };
  const group = (a) => (a.earned ? 2 : frac(a) === null ? 1 : 0);
  return out.sort((x, y) => {
    const gx = group(x), gy = group(y);
    if (gx !== gy) return gx - gy;
    if (gx === 0) {
      const fx = frac(x), fy = frac(y);
      if (fx !== fy) return fy - fx;
      const px = Number(x.points) || 0, py = Number(y.points) || 0;
      if (px !== py) return py - px;
    }
    return byOrder(x, y);
  });
}

/* ---- Small Calls L2: relics by kind --------------------------------------------------- */

/* One row per kind, in this order, each HIDDEN when the account has earned nothing of that
   kind: nothing unearned is ever listed, so there are no empty slots and no locked tiles.
   A relic is a reward an honor awarded, so the free skins and the free marks every account
   starts with are not relics. Newest first within a row, by the day the awarding honor was
   earned (a relic with no recorded day follows the dated ones).

     skins    the skins the payload lists as earned and as awarded by an unlock
     banners  the earned honors that award a banner
     marks    `relics.marks`, the server's earned, awarded marks

   Each item: {id, name, desc, date, active?, png?, animated?}. */
export function relicRows({ skins, achievements, marks, earnedAt, activeSkin } = {}) {
  const at = earnedAt || {};
  const achs = Array.isArray(achievements) ? achievements : [];
  const dateOf = (id) => (typeof at[id] === "string" ? at[id] : "");
  const newestFirst = (items) => items
    .map((it, i) => ({ it, i }))
    .sort((x, y) => {
      const dx = x.it.date, dy = y.it.date;
      if (dx !== dy) return dx === "" ? 1 : dy === "" ? -1 : (dx < dy ? 1 : -1);
      return x.i - y.i;
    })
    .map((x) => x.it);

  const skinItems = (Array.isArray(skins) ? skins : [])
    .filter((s) => s && s.earned && typeof s.unlock === "string" && s.unlock)
    .map((s) => {
      const giver = achs.find((a) => a.earned && a.skin === s.id);
      return { id: s.id, name: s.name, desc: s.desc || "", date: giver ? dateOf(giver.id) : "",
        active: s.id === activeSkin };
    });
  const bannerItems = achs
    .filter((a) => a.earned && a.banner_reward)
    .map((a) => ({ id: a.id, name: a.name, desc: a.desc || "", date: dateOf(a.id) }));
  const markItems = (Array.isArray(marks) ? marks : [])
    .filter((m) => m && m.id)
    .map((m) => ({ id: m.id, name: m.label || m.id, desc: "", date: dateOf(m.unlock),
      png: m.png || "", animated: !!m.animated }));

  return [
    { kind: "skins", label: "Skins", items: newestFirst(skinItems) },
    { kind: "banners", label: "Banners", items: newestFirst(bannerItems) },
    { kind: "marks", label: "Marks", items: newestFirst(markItems) },
  ].filter((row) => row.items.length > 0);
}

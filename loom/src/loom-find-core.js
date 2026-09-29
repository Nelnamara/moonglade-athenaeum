/* =========================================================================
   loom-find-core.js — FIND IN STORYBOARD (Session P, NOTES P8), as pure views.

   The page (Loom Handoff.dc.html, section B, P8): "⌘/Ctrl F focuses the field. It matches
   shot code, title, prompt, cast @tags and notes. Filter chips narrow the results (⚠ only ·
   status · mode). Non-matching cards dim to 35%, matches ring lavender on the reel, and ↑ ↓ /
   Enter step through them, with the current one ringed brighter. Esc clears it."

   Find is a VIEW over the board: nothing here (or in the app's runFind / stepFind / clearFind)
   writes the board, prices or renders -- loom/test/loom-no-auto-render.test.js roots the
   handlers and pins that this module reaches nothing. Same discipline as loom-core.js: NO
   React, no DOM, no window, no fetch.

   THE RULES
     * A query is ONE case-insensitive substring (trimmed). It matches a shot when it is found
       in any of: the shot's code in each of its written forms ("A·01", "A01", "a1" -- the "·"
       dropped, and the number with and without its leading zero), its title, its prompt (the
       text it sends -- effectivePrompt -- and the base prompt under an override), the @tags
       of its cast members, and its notes. An empty query matches every shot.
     * Filters narrow: "⚠ only" keeps a shot whose anchor is stale (P2), plus any ⚠ the card
       itself shows that the caller can compute (opts.warn); the status chips and the mode
       chips each keep a shot matching ANY chip ticked in that group; the groups (and the
       query) must ALL hold. `only` (a list of shot ids) restricts to exactly those shots --
       the continuity ribbon's "open both" (P9).
   ========================================================================================= */
import { effectivePrompt } from "./loom-core.js";
import { anchorState } from "./loom-takes-core.js";

/** The statuses and modes a chip can name, in the order the chips show. */
export const FIND_STATUSES = ["todo", "wip", "done", "paused", "error"];
export const FIND_MODES = ["I2V", "R2V", "FLF", "V2V"];

const low = (v) => String(v == null ? "" : v).toLowerCase();

/** Every written form of a shot code: "A·01" -> ["a·01", "a01", "a1"]. */
export const codeForms = (code) => {
  const c = low(code).trim();
  if (!c) return [];
  const parts = c.split("·");
  if (parts.length !== 2) return [c];
  const [act, num] = parts;
  const bare = /^\d+$/.test(num) ? String(Number(num)) : num;
  return Array.from(new Set([act + "·" + num, act + num, act + bare]));
};

/** The text a query is looked for in, one string per field. */
export const findFields = (entry, project) => {
  const c = (entry && entry.c) || {};
  const tags = ((project && project.assets) || []).filter((a) => a && (c.cast || []).includes(a.id)).map((a) => low(a.tag));
  return [...codeForms(entry && entry.code), low(c.title), low(effectivePrompt(c)), low(c.prompt), ...tags, low(c.notes)];
};

/** An empty find: no query, no chip, no pair. */
export const emptyFind = () => ({ q: "", warn: false, statuses: [], modes: [], only: null, cur: 0 });

/** Is anything being looked for? (Only then do cards dim and the reel ring.) */
export const findActive = (f) => !!(f && (String(f.q || "").trim() || f.warn || (f.statuses || []).length
  || (f.modes || []).length || (f.only && f.only.length)));

/**
 * findMatches(entries, project, query, filters, opts) -> [shot id], board order.
 *   entries   flat(project)
 *   filters   {warn, statuses:[..], modes:[..], only:[ids]|null}
 *   opts      {byId: Map(id -> card) for the stale test, statusOf(card) (default card.status),
 *              warn(entry) -> bool for the card's own ⚠ chips}
 */
export const findMatches = (entries, project, query, filters, opts) => {
  const q = low(query).trim();
  const f = filters || {};
  const o = opts || {};
  const byId = o.byId || new Map((entries || []).map((e) => [e.c.id, e.c]));
  const statusOf = o.statusOf || ((c) => c.status);
  const statuses = f.statuses || [], modes = f.modes || [];
  const only = f.only && f.only.length ? new Set(f.only) : null;
  return (entries || []).filter((e) => {
    const c = e.c || {};
    if (only && !only.has(c.id)) return false;
    if (q && !findFields(e, project).some((t) => t.includes(q))) return false;
    if (f.warn && !(anchorState(c, byId) === "stale" || (o.warn && o.warn(e)))) return false;
    if (statuses.length && !statuses.includes(statusOf(c))) return false;
    if (modes.length && !modes.includes(c.mode)) return false;
    return true;
  }).map((e) => e.c.id);
};

/** The chips to show: ⚠ only, then the statuses and modes that occur on this board. */
export const findChips = (entries, opts) => {
  const statusOf = (opts && opts.statusOf) || ((c) => c.status);
  const st = new Set((entries || []).map((e) => statusOf(e.c)));
  const md = new Set((entries || []).map((e) => e.c.mode));
  return [{ kind: "warn", key: "warn", label: "⚠ only" }]
    .concat(FIND_STATUSES.filter((s) => st.has(s)).map((s) => ({ kind: "status", key: s, label: s })))
    .concat(FIND_MODES.filter((m) => md.has(m)).map((m) => ({ kind: "mode", key: m, label: m })));
};

/** Is this chip on? */
export const chipOn = (f, chip) => (chip.kind === "warn" ? !!(f && f.warn)
  : chip.kind === "status" ? ((f && f.statuses) || []).includes(chip.key)
  : ((f && f.modes) || []).includes(chip.key));

/** The find with one chip flipped (the current match goes back to the first). */
export const toggleChip = (f, chip) => {
  const base = { ...emptyFind(), ...(f || {}), cur: 0 };
  if (chip.kind === "warn") return { ...base, warn: !base.warn };
  const k = chip.kind === "status" ? "statuses" : "modes";
  const has = base[k].includes(chip.key);
  return { ...base, [k]: has ? base[k].filter((x) => x !== chip.key) : base[k].concat([chip.key]) };
};

/** Which match is current: `cur` wraps both ways. -1 when nothing matches. */
export const currentIndex = (cur, n) => (n > 0 ? (((Number(cur) || 0) % n) + n) % n : -1);

/** One step (dir = +1 / -1), wrapping. */
export const stepIndex = (cur, n, dir) => (n > 0 ? currentIndex((Number(cur) || 0) + (dir < 0 ? -1 : 1), n) : 0);

/** The count the pill shows: "2 of 5", "0", or "" when nothing is being looked for. */
export const findCountText = (f, n) => {
  if (!findActive(f)) return "";
  if (!n) return "0";
  return (currentIndex(f.cur, n) + 1) + " of " + n;
};

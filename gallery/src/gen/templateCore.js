/* The prompt template, the send routing, the run confirm's words and the run's read-back
   (Session M, Generate power tools: NOTES 1, 2, 3, 8; Generate Power Tools Handoff).

   ONE SYNTAX for Random and Matrix: `{a|b|c}` is an inline variable, `__name__` reads a
   saved list, `\{` `\}` `\_` are literal. This file is the dock's copy of the rule; the
   server's is moonglade_runs.py, and tests/fixtures/template_vectors.json pins both to one
   set of answers (loom/test/template-core.test.js + tests/test_generate_runs.py), so the
   preview the dock draws is the set of jobs the server sends.

   THE DOCK ONLY DRAWS WITH IT. The server re-parses, re-expands, re-counts, re-caps,
   re-builds and re-quotes every run itself (BUILD-w5-m s3); nothing computed here is sent as
   data except the confirm's acknowledgement, which the server checks against its own fresh
   quote. Pure: no DOM, no fetch, no React. */

export const MAX_VARS = 8;
export const MAX_OPTIONS = 64;
export const CELL_CAP = 24;
export const MAX_COUNT = 4;
export const RUN_SEED_MAX = 2147483646;
export const SEED_MOD = 2147483647;
export const LISTS_KEY = "gen.lists";
export const LIST_NAME_RE = /^[a-z0-9_]{1,32}$/;
export const MAX_LISTS = 50;
export const MAX_LIST_ITEMS = 200;
export const LIST_ITEM_MAX = 200;
const BIG = 1000000;

export const ERR_UNCLOSED = "Unclosed or nested brace. Nesting isn’t supported.";
export const ERR_STRAY = "Stray closing brace — write \\} for a literal one.";
export const ERR_EMPTY = "Empty variable.";
export const ERR_TOO_MANY_VARS = "Up to " + MAX_VARS + " variables in one prompt.";
export const ERR_TOO_MANY_OPTS = "Up to " + MAX_OPTIONS + " options in one variable.";
export const errUnknownList = (t) => "No list named " + t + ".";
export const errEmptyList = (t) => "The list " + t + " is empty.";
export const errLongList = (t) => "The list " + t + " is too long — up to " + MAX_LIST_ITEMS
  + " items of up to " + LIST_ITEM_MAX + " characters.";
export const errDuplicate = (t, v) => t + " has ‘" + v + "’ twice — a matrix would pay for the same cell twice.";
export const errBlankCell = (n) => "Cell " + n + "’s prompt is empty.";
export function errOverCap(product) {
  if (product > BIG) return "More than a million combinations is over the " + CELL_CAP + "-cell cap — narrow an axis.";
  return fmt(product) + " combinations is over the " + CELL_CAP + "-cell cap — narrow an axis.";
}

/* Thousands separators, the same in every locale (the server uses Python's {:,}). */
export function fmt(n) {
  const s = String(Math.trunc(Number(n) || 0));
  const neg = s.startsWith("-");
  const d = neg ? s.slice(1) : s;
  return (neg ? "-" : "") + d.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

const LIST_TOKEN_RE = /__([a-z0-9_]+)__/y;

/* A saved list's items as the expander uses them: trimmed, blank lines dropped. null when it
   is not a list of strings or breaks the bounds (refused, never cut). */
export function cleanList(items) {
  if (!Array.isArray(items)) return null;
  const out = [];
  for (const it of items) {
    if (typeof it !== "string") return null;
    const t = it.trim();
    if (!t) continue;
    if (t.length > LIST_ITEM_MAX) return null;
    out.push(t);
  }
  return out.length > MAX_LIST_ITEMS ? null : out;
}

/* The account's lists out of its prefs document (bad names skipped). */
export function listsFromPrefs(prefs) {
  const raw = prefs && prefs[LISTS_KEY];
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out = {};
  for (const k of Object.keys(raw)) if (LIST_NAME_RE.test(k)) out[k] = raw[k];
  return out;
}

/* The Lists sheet's text (one item per line) -> the items it saves. */
export function listItemsFromText(text) {
  return String(text || "").split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
}

/* Why the Lists sheet may not save this list, or "" (the same bounds the server expands by). */
export function listProblem(name, items, lists) {
  const n = String(name || "");
  if (!LIST_NAME_RE.test(n)) return "A list name is lowercase letters, digits and _ (up to 32).";
  if (!Array.isArray(items) || !items.length) return "Add at least one item, one per line.";
  if (items.length > MAX_LIST_ITEMS) return "Up to " + MAX_LIST_ITEMS + " items in a list.";
  if (items.some((x) => x.length > LIST_ITEM_MAX)) return "Each item is up to " + LIST_ITEM_MAX + " characters.";
  const others = Object.keys(lists || {}).filter((k) => k !== n);
  if (others.length >= MAX_LISTS) return "Up to " + MAX_LISTS + " lists.";
  return "";
}

/* Scan left to right, once -> {parts, vars, error, syntax}. The same rule as
   moonglade_runs.parse (see that docstring). */
export function parse(template, lists) {
  const s = String(template == null ? "" : template);
  const L = lists || {};
  const parts = [];
  let error = null, syntax = false, nvars = 0;
  let buf = "";
  const flush = () => { if (buf) { parts.push({ lit: buf }); buf = ""; } };
  const bad = (token, msg) => { flush(); parts.push({ bad: token, error: msg }); if (error === null) error = msg; };
  const addVar = (part) => {
    flush();
    nvars += 1;
    if (nvars > MAX_VARS) {
      parts.push({ bad: part.var, error: ERR_TOO_MANY_VARS });
      if (error === null) error = ERR_TOO_MANY_VARS;
      return;
    }
    parts.push(part);
  };
  const n = s.length;
  let i = 0;
  while (i < n) {
    const c = s[i];
    if (c === "\\" && i + 1 < n && "{}_".includes(s[i + 1])) {
      buf += s[i + 1]; syntax = true; i += 2; continue;
    }
    if (c === "{") {
      syntax = true;
      let j = i + 1;
      while (j < n && s[j] !== "{" && s[j] !== "}") j += 1;
      if (j >= n || s[j] === "{") { bad("{", ERR_UNCLOSED); i += 1; continue; }
      const token = s.slice(i, j + 1);
      const opts = s.slice(i + 1, j).split("|").map((o) => o.trim()).filter(Boolean);
      if (!opts.length) bad(token, ERR_EMPTY);
      else if (opts.length > MAX_OPTIONS) bad(token, ERR_TOO_MANY_OPTS);
      else addVar({ var: token, options: opts, kind: "inline" });
      i = j + 1;
      continue;
    }
    if (c === "}") { syntax = true; bad("}", ERR_STRAY); i += 1; continue; }
    if (c === "_") {
      LIST_TOKEN_RE.lastIndex = i;
      const m = LIST_TOKEN_RE.exec(s);
      if (m) {
        syntax = true;
        const token = m[0], name = m[1];
        if (!Object.prototype.hasOwnProperty.call(L, name)) bad(token, errUnknownList(token));
        else {
          const items = cleanList(L[name]);
          if (items === null) bad(token, errLongList(token));
          else if (!items.length) bad(token, errEmptyList(token));
          else addVar({ var: token, options: items, kind: "list", name });
        }
        i = LIST_TOKEN_RE.lastIndex;
        continue;
      }
    }
    buf += c;
    i += 1;
  }
  flush();
  return { parts, vars: parts.filter((p) => p.var != null), error, syntax };
}

export function hasSyntax(template) { return parse(template, null).syntax; }

function resolve(parts, values) {
  let out = "", k = 0;
  for (const p of parts) {
    if (p.lit != null) out += p.lit;
    else if (p.var != null) { out += values[k]; k += 1; }
  }
  return out;
}

/* The page's LCG (rng()): exact in doubles because s * 1664525 + 1013904223 < 2^53. */
export function rng(runSeed) {
  let s = (Number(runSeed) >>> 0) || 1;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s; };
}
const pick = (s, len) => Math.floor((s / 4294967296) * len);

export function matrixProduct(vars) {
  let p = 1;
  for (const v of vars) {
    p *= v.options.length;
    if (p > BIG) return BIG + 1;
  }
  return p;
}

/* Expand a template into its jobs -- moonglade_runs.plan_jobs, the same shape:
   {error} or {mode: single|batch|random|matrix, images, product, axes?, jobs: [{cell, prompt,
   vars: [{token, value}], seed (null = the dock's own seed field), batch}]}. */
export function planJobs(template, lists, varMode, count, runSeed) {
  const P = parse(template, lists);
  if (P.error) return { error: P.error };
  const vars = P.vars;
  if (!vars.length) {
    const batch = varMode === "random" ? count : 1;
    return { mode: batch > 1 ? "batch" : "single", images: batch, product: 1,
      jobs: [{ cell: 0, prompt: resolve(P.parts, []), vars: [], seed: null, batch }] };
  }
  const jobs = [];
  let mode, axes = null;
  const product = matrixProduct(vars);
  if (varMode === "matrix") {
    if (product > CELL_CAP) return { error: errOverCap(product), product };
    for (const v of vars) {
      const seen = new Set();
      for (const o of v.options) {
        if (seen.has(o)) return { error: errDuplicate(v.var, o) };
        seen.add(o);
      }
    }
    for (let i = 0; i < product; i++) {
      let r = i;
      const vals = [];
      for (let k = vars.length - 1; k >= 0; k--) {
        const opts = vars[k].options;
        vals.unshift(opts[r % opts.length]);
        r = Math.floor(r / opts.length);
      }
      jobs.push({ cell: i, prompt: resolve(P.parts, vals),
        vars: vars.map((v, k) => ({ token: v.var, value: vals[k] })), seed: null, batch: 1 });
    }
    mode = "matrix";
    axes = vars.map((v) => ({ token: v.var, values: v.options.slice() }));
  } else {
    const next = rng(runSeed);
    for (let k = 0; k < count; k++) {
      const vals = vars.map((v) => v.options[pick(next(), v.options.length)]);
      jobs.push({ cell: k, prompt: resolve(P.parts, vals),
        vars: vars.map((v, j) => ({ token: v.var, value: vals[j] })),
        seed: (Number(runSeed) + k) % SEED_MOD, batch: 1 });
    }
    mode = "random";
  }
  for (const j of jobs) if (!j.prompt.trim()) return { error: errBlankCell(j.cell + 1) };
  const out = { mode, images: jobs.length, product, jobs };
  if (axes) out.axes = axes;
  return out;
}

/* A plain prompt made safe to put back in the composer (moonglade_runs.escape_literal). */
export function escapeLiteral(text) {
  const s = String(text || "");
  let out = "";
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c === "{" || c === "}") out += "\\" + c;
    else if (c === "_" && ((i > 0 && (s[i - 1] === "_" || s[i - 1] === "\\")) || s[i + 1] === "_")) out += "\\_";
    else out += c;
  }
  return out;
}

/* ---- the dock's side ---------------------------------------------------------------- */

/* The run seed: the seed field when it holds a seed in range, else the dock's roll. null when
   the field holds something a Random run cannot use (the server refuses it the same way). */
export function runSeedOf(seedField, roll) {
  const f = String(seedField == null ? "" : seedField).trim();
  if (/^-?\d{1,12}$/.test(f)) {
    const v = Number(f);
    return v >= 0 && v <= RUN_SEED_MAX ? v : null;
  }
  const r = Number(roll);
  return Number.isInteger(r) && r >= 0 && r <= RUN_SEED_MAX ? r : null;
}

/* A fresh roll (the dock's ⚄ Reroll and the value drawn when it opens). */
export function newRoll(rand) {
  const r = typeof rand === "function" ? rand() : Math.random();
  return Math.floor(r * (RUN_SEED_MAX + 1));
}

/* Where a Send goes (NOTES 2): "blocked" (a template refusal), "generate" (one generation,
   plain text: today's /api/generate, unchanged), "run" (one generation whose prompt uses the
   syntax: /api/generate/run with no acknowledgement) or "confirm" (more than one: /plan, the
   confirm, then /run). `plan` is planJobs' answer for the dock's state. */
export function sendRoute(plan, syntax) {
  if (!plan || plan.error) return "blocked";
  if (plan.images > 1) return "confirm";
  return syntax ? "run" : "generate";
}

/* The dock's line beside Send (the page's sendSummary). */
export function sendSummary(parsed, plan, varMode, count) {
  if (parsed.error) return "⚠ " + parsed.error;
  const vars = parsed.vars;
  const product = matrixProduct(vars);
  const combos = vars.length ? vars.map((v) => v.options.length).join(" × ") + " = "
    + (product > BIG ? "over a million" : fmt(product)) + " combinations" : "no variables";
  if (plan && plan.error) return "⚠ " + plan.error;
  if (varMode === "matrix") return combos + " · every one is sent, queued";
  return combos + " · " + count + " drawn at random";
}

/* The token line under the prompt: literal text plain, a variable lavender with its option
   count, a refusal peach (page M1). */
export function tokenLine(parsed) {
  return parsed.parts.map((p) => p.lit != null ? { t: p.lit, kind: "lit" }
    : p.var != null ? { t: p.var + " ·" + p.options.length, kind: "var" }
      : { t: p.bad, kind: "bad", why: p.error });
}

/* The preview rows ("PREVIEW · what each image will get"): up to six, then "… N more". */
export function previewRows(plan, limit) {
  const max = limit || 6;
  if (!plan || plan.error) {
    return plan && plan.product > CELL_CAP ? ["(" + (plan.product > BIG ? "over a million" : fmt(plan.product))
      + " cells — nothing is sent above " + CELL_CAP + ")"] : [];
  }
  const rows = plan.jobs.slice(0, max).map((j, i) => (i + 1) + "  " + j.prompt);
  if (plan.jobs.length > max) rows.push("… " + (plan.jobs.length - max) + " more");
  return rows;
}

/* The acknowledgement the confirm's Go sends back: copied from the /plan answer. */
export function ackOf(plan) {
  return { count: plan.count, jobs: plan.jobs, each: plan.each, covered: plan.covered,
    total: plan.total, digest: plan.digest };
}

/* The ONE confirm's words (page "$", NOTES 2), from the server's own quote:
   {title, credits, cards, note, go, blocked}. */
export function confirmCopy(plan) {
  const p = plan || {};
  const n = Number(p.count) || 0;
  const jobs = Number(p.jobs) || 0;
  const matrix = p.mode === "matrix";
  const title = "Send " + n + " generations?" + (matrix ? " (matrix, queued)" : "");
  let credits;
  if (p.unlimited) credits = "free · Unlimited Mode";
  else if (p.mode === "batch") credits = "≈ " + fmt(p.total) + " credits in total · one task of " + n + " images";
  else credits = "≈ " + fmt(p.total) + " credits in total · " + fmt(p.each) + " each × " + (jobs - (Number(p.covered) || 0));
  let cards;
  const covered = Number(p.covered) || 0;
  const left = p.card && p.card.left_after != null ? " · " + fmt(p.card.left_after) + " left after" : "";
  if (p.unlimited) cards = "No free card is used in Unlimited Mode.";
  else if (matrix) cards = "Free cards don’t cover queued matrix runs.";
  else if (covered && p.mode === "batch") cards = "A free card covers this batch" + left;
  else if (covered) cards = covered + " free card" + (covered > 1 ? "s cover the first " + covered : " covers the first") + left;
  else cards = "No free card covers this.";
  if (p.card_note && p.card_note !== cards) cards += " (" + p.card_note + ")";
  const notes = [];
  if (jobs > 1) notes.push("Each prompt is checked by PixAI as it goes out; if it refuses one, the rest aren’t sent.");
  if (p.read_only) notes.push("READ_ONLY is on in config.json, so nothing can be sent.");
  return { title, credits, cards, note: notes.join(" "), go: "Send " + n, blocked: !!p.read_only };
}

/* ---- after Go: the run's line and its read-back ---------------------------------------- */

const cellName = (j) => "Cell " + (Number(j.cell) + 1);
function range(a, b) { return a === b ? "Cell " + a + " was" : "Cells " + a + "–" + b + " were"; }

/* The result line (s4.4): "Sent 7 of 24. Cell 8 was refused by PixAI: <reason>. Cells 9–24
   were not sent." `kind`: ok | warn (peach: a refusal, an unclear job, a stop). Nothing on
   this line re-sends anything. */
export function runLine(res) {
  const r = res || {};
  const jobs = Array.isArray(r.jobs) ? r.jobs : [];
  const total = jobs.length;
  const sent = jobs.filter((j) => j.state === "sent").length;
  if (r.error && !jobs.length) return { text: r.error, kind: "warn" };
  if (total <= 1) {
    const j = jobs[0] || {};
    if (j.state === "sent") return { text: r.mode === "batch" ? "Sent — " + (r.count || 1) + " images in one task." : "Sent.", kind: "ok" };
    if (j.state === "refused") return { text: "PixAI refused it: " + (j.error || "no reason given") + ". Nothing was made.", kind: "warn" };
    if (j.state === "may_have_started") return { text: "This one may have started on PixAI — check the Activity tray before sending again.", kind: "warn" };
    return { text: "Not sent: " + (j.error || r.reason || "stopped") + ".", kind: "warn" };
  }
  const bits = ["Sent " + sent + " of " + total + "."];
  const fail = jobs.find((j) => j.state === "refused" || j.state === "may_have_started"
    || (j.state === "not_sent" && j.error));
  if (fail) {
    if (fail.state === "refused") bits.push(cellName(fail) + " was refused by PixAI: " + (fail.error || "no reason given") + ".");
    else if (fail.state === "may_have_started") bits.push(cellName(fail) + " may have started on PixAI — check the Activity tray before sending again.");
    else bits.push(cellName(fail) + " was not sent: " + fail.error);
  } else if (r.status === "stopped" && r.reason) {
    bits.push(r.reason);
  }
  const rest = jobs.filter((j) => j.state === "not_sent" && j !== fail).map((j) => Number(j.cell) + 1);
  if (rest.length) bits.push(range(rest[0], rest[rest.length - 1]) + " not sent.");
  return { text: bits.join(" "), kind: sent === total ? "ok" : "warn" };
}

/* A charge that differs from what the confirm said (review F14), as one peach sentence. */
export function chargeMismatch(cellNo, expected, paid) {
  if (expected == null || paid == null || Number(expected) === Number(paid)) return "";
  return "Cell " + cellNo + " cost " + fmt(paid) + " credits; the confirm expected "
    + (Number(expected) === 0 ? "it free" : fmt(expected)) + ".";
}

export const READBACK_LOST_MS = 30000;
export const TERMINAL = ["sent", "stopped", "refused"];

/* The run's read-back (review F4), a pure reducer. The dock POSTs /run ONCE and never again
   for that run_id; while the POST is out it reads GET /api/generate/runs/<id> every 2 s.
     state: {phase: "posting" | "reading" | "done" | "lost", since, run}
     event: {type: "get404" | "get" | "post" | "postLost", run?, at}
   - a 404 while the POST is out means "not received yet" -- keep waiting;
   - a run from either answer that is terminal ends it ("done");
   - a lost POST (transport error) turns to reading back; a 404 that lasts READBACK_LOST_MS
     after that is "lost": "may not have reached the server", never "not sent".
   Send stays disabled until the phase is done or lost. */
export function readBack(state, ev) {
  const s = state || { phase: "posting", since: ev && ev.at, run: null };
  if (s.phase === "done" || s.phase === "lost") return s;
  const at = Number(ev && ev.at) || 0;
  switch (ev && ev.type) {
    case "post":
      return { phase: "done", since: at, run: ev.run };
    case "postLost":
      return { phase: "reading", since: at, run: s.run };
    case "get": {
      const run = ev.run;
      if (run && TERMINAL.includes(run.status)) return { phase: "done", since: at, run };
      return { ...s, run };
    }
    case "get404":
      if (s.phase === "reading" && !s.run && at - s.since >= READBACK_LOST_MS) {
        return { phase: "lost", since: at, run: null };
      }
      return s;
    default:
      return s;
  }
}

export const LOST_WORDS = "This run may not have reached the server — check the Activity tray before sending again.";

/* The matrix reel grid (NOTES 8, page M6): the last axis across, the rest down. `cells`
   indexes by cell number. -> {across, rows: [{label, cells: [cell | null]}]} */
export function matrixGrid(axes, cells) {
  const ax = Array.isArray(axes) ? axes : [];
  if (!ax.length) return null;
  const across = ax[ax.length - 1].values || [];
  const cols = across.length || 1;
  const total = ax.reduce((a, x) => a * ((x.values || []).length || 1), 1);
  const rows = [];
  const byCell = {};
  for (const c of cells || []) if (c && c.cell != null) byCell[c.cell] = c;
  for (let r = 0; r < total / cols; r++) {
    // the row's label: every axis but the last, read off the first cell's index
    let rem = r * cols;
    const vals = [];
    for (let k = ax.length - 1; k >= 0; k--) {
      const v = ax[k].values || [];
      vals.unshift(v[rem % v.length]);
      rem = Math.floor(rem / v.length);
    }
    const row = [];
    for (let c = 0; c < cols; c++) row.push(byCell[r * cols + c] || null);
    rows.push({ label: vals.slice(0, -1).join(" · ") || "—", cells: row });
  }
  return { across, rows };
}

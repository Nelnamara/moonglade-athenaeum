/* The prompt template, the send routing, the run confirm's words and the run's read-back
   (Session M, Generate power tools: NOTES 1, 2, 3, 8; Generate Power Tools Handoff).

   ONE SYNTAX for Random and Matrix: `{a|b|c}` is an inline variable, `__name__` reads a
   saved list; a brace group with no `|` is literal text, and a backslash is dropped only
   where it changes the parse (the S1 ruling, see parse). This file is the dock's copy of the rule; the
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
export const RUN_SEED_MAX = 2147483646;
export const SEED_MOD = 2147483647;
export const LISTS_KEY = "gen.lists";
export const LIST_NAME_RE = /^[a-z0-9_]{1,32}$/;
export const MAX_LISTS = 50;
export const MAX_LIST_ITEMS = 200;
export const LIST_ITEM_MAX = 200;
const BIG = 1000000;

export const ERR_UNCLOSED = "Unclosed or nested brace. Nesting isn’t supported.";
export const ERR_EMPTY = "Empty variable.";

/* What an option and a list item are trimmed of (review N5): ONE explicit set, the same as
   moonglade_runs.TRIM_CHARS, because String.trim() and Python's str.strip() disagree (JS keeps
   U+0085 and U+001C-U+001F, Python keeps U+FEFF). It is the union of the two. */
export const TRIM_CHARS = "\t\n\u000b\u000c\r\u001c\u001d\u001e\u001f \u0085  "
  + "           "
  + "    　﻿";
const TRIM_RE = new RegExp("^[" + TRIM_CHARS + "]+|[" + TRIM_CHARS + "]+$", "g");
export function trim(text) { return String(text).replace(TRIM_RE, ""); }
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
    const t = trim(it);
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
  return String(text || "").split(/\r?\n/).map(trim).filter(Boolean);
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

/* The raw brace structure, every backslash ignored (moonglade_runs._brace_structure):
   {pairs: Map open -> close, parent: Map open -> enclosing open | null, unclosed: [opens]}. */
function braceStructure(s) {
  const stack = [], pairs = new Map(), parent = new Map();
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c === "{") { parent.set(i, stack.length ? stack[stack.length - 1] : null); stack.push(i); }
    else if (c === "}" && stack.length) pairs.set(stack.pop(), i);
  }
  return { pairs, parent, unclosed: stack };
}

/* [has a top-level |, holds a nested pair] for the pair (o, c). */
function pairShape(s, o, c, pairs) {
  let i = o + 1, pipe = false, child = false;
  while (i < c) {
    const ch = s[i];
    if (ch === "{") { child = true; i = pairs.get(i) + 1; continue; }
    if (ch === "|") pipe = true;
    i += 1;
  }
  return [pipe, child];
}

/* Where the template rule acts (moonglade_runs._template_marks): groups (open -> [kind,
   close], kind live | escaped | nested) for every pair holding a top-level |, the backslash
   positions dropped, and the unclosed { refused. Every other brace is literal text and every
   other backslash stays. */
function templateMarks(s) {
  const { pairs, parent, unclosed } = braceStructure(s);
  const groups = new Map(), consume = new Set(), badOpen = new Set();
  const esc = (k) => k > 0 && s[k - 1] === "\\";
  for (const [o, c] of pairs) {
    const [pipe, child] = pairShape(s, o, c, pairs);
    if (!pipe) continue;
    if (esc(o) || esc(c)) {
      groups.set(o, ["escaped", c]);
      if (esc(o)) consume.add(o - 1);
      if (esc(c)) consume.add(c - 1);
    } else if (child || pairs.has(parent.get(o))) {
      groups.set(o, ["nested", c]);
    } else {
      groups.set(o, ["live", c]);
    }
  }
  for (const u of unclosed) {
    if (s.indexOf("|", u + 1) >= 0) {
      if (esc(u)) consume.add(u - 1);
      else badOpen.add(u);
    }
  }
  return { groups, consume, badOpen };
}

/* Scan left to right, once -> {parts, vars, error, syntax}. The same rule as
   moonglade_runs.parse (the S1 ruling -- see that docstring): a {...} group is a variable only
   when it holds a top-level |; a brace group with no | is literal text, sent as typed; a
   backslash is dropped only where it changes the parse (before the { or } of a | group,
   before an unclosed { with a | after it, before the __ of a list token); an unclosed { with a
   | after it and a nested | group are refused. A prompt with no | group and no __name__ token
   resolves to itself byte for byte. */
export function parse(template, lists) {
  const s = String(template == null ? "" : template);
  const L = lists || {};
  const parts = [];
  let error = null, syntax = false, nvars = 0;
  let buf = "";
  const { groups, consume, badOpen } = templateMarks(s);
  const flush = () => { if (buf) { parts.push({ lit: buf }); buf = ""; } };
  // `at` is the token's [start, end) in the raw template -- what promptTint cuts the box by.
  const bad = (token, msg, at) => { flush(); parts.push({ bad: token, error: msg, at }); if (error === null) error = msg; };
  const addVar = (part) => {
    flush();
    nvars += 1;
    if (nvars > MAX_VARS) {
      parts.push({ bad: part.var, error: ERR_TOO_MANY_VARS, at: part.at });
      if (error === null) error = ERR_TOO_MANY_VARS;
      return;
    }
    parts.push(part);
  };
  const n = s.length;
  let i = 0;
  while (i < n) {
    const c = s[i];
    if (consume.has(i)) { syntax = true; i += 1; continue; }   // a backslash that changes the parse
    if (c === "\\") {
      LIST_TOKEN_RE.lastIndex = i + 1;
      const m = LIST_TOKEN_RE.exec(s);
      if (m) { buf += m[0]; syntax = true; i = LIST_TOKEN_RE.lastIndex; continue; }   // \__name__ is literal
      buf += c; i += 1; continue;
    }
    if (c === "{") {
      const g = groups.get(i);
      if (g && g[0] === "live") {
        syntax = true;
        const j = g[1];
        const token = s.slice(i, j + 1);
        const at = [i, j + 1];
        const opts = s.slice(i + 1, j).split("|").map(trim).filter(Boolean);
        if (!opts.length) bad(token, ERR_EMPTY, at);
        else if (opts.length > MAX_OPTIONS) bad(token, ERR_TOO_MANY_OPTS, at);
        else addVar({ var: token, options: opts, kind: "inline", at });
        i = j + 1;
        continue;
      }
      if (g && g[0] === "nested") { syntax = true; bad(s.slice(i, g[1] + 1), ERR_UNCLOSED, [i, g[1] + 1]); i = g[1] + 1; continue; }
      if (badOpen.has(i)) { syntax = true; bad("{", ERR_UNCLOSED, [i, i + 1]); i += 1; continue; }
      buf += c; i += 1; continue;   // a literal brace (an escaped group's too)
    }
    if (c === "_") {
      LIST_TOKEN_RE.lastIndex = i;
      const m = LIST_TOKEN_RE.exec(s);
      if (m) {
        syntax = true;
        const token = m[0], name = m[1];
        const at = [i, i + token.length];
        if (!Object.prototype.hasOwnProperty.call(L, name)) bad(token, errUnknownList(token), at);
        else {
          const items = cleanList(L[name]);
          if (items === null) bad(token, errLongList(token), at);
          else if (!items.length) bad(token, errEmptyList(token), at);
          else addVar({ var: token, options: items, kind: "list", name, at });
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
  for (const j of jobs) if (!trim(j.prompt)) return { error: errBlankCell(j.cell + 1) };
  const out = { mode, images: jobs.length, product, jobs };
  if (axes) out.axes = axes;
  return out;
}

/* True when a send of `plan` goes out with no free card whatever the payload says: a Matrix of
   2 or more cells (Settled 2). A one-cell matrix is an ordinary single send (review B1). The
   dock's cost badge prices with no_card on exactly when this is true
   (moonglade_runs.forces_no_card). */
export function forcesNoCard(plan) {
  return !!plan && !plan.error && plan.mode === "matrix" && Array.isArray(plan.jobs) && plan.jobs.length >= 2;
}

/* How many sends the dock's ONE price quote stands for (owner walk 2026-09-29: a Matrix of 3
   quoted the price of 1). The badge prices one request; a Matrix of 2 or more cells sends that
   request once per cell -- every cell costs the same, or the server refuses the run -- so the
   cost line multiplies by the cells and says the total the confirm will say. Anything else is
   1: a Random run and a plain batch are priced whole, their count rides in the request. */
export function quoteSends(plan) {
  return forcesNoCard(plan) ? plan.jobs.length : 1;
}

/* A plain prompt made safe to put back in the composer (moonglade_runs.escape_literal): only
   what the rule would act on gets a backslash -- the { of every | group (and its } when a
   backslash already sits before it), an unclosed { with a | after it, the first _ of every
   list token. Ordinary braces, long_hair and a kaomoji's \_ stay exactly as they are. */
export function escapeLiteral(text) {
  const s = String(text || "");
  const n = s.length;
  const { pairs, unclosed } = braceStructure(s);
  const ins = new Set();
  for (const [o, c] of pairs) {
    if (pairShape(s, o, c, pairs)[0]) {
      ins.add(o);
      if (s[c - 1] === "\\") ins.add(c);
    }
  }
  for (const u of unclosed) if (s.indexOf("|", u + 1) >= 0) ins.add(u);
  let i = 0;
  while (i < n) {
    if (s[i] === "_") {
      LIST_TOKEN_RE.lastIndex = i;
      const m = LIST_TOKEN_RE.exec(s);
      if (m) { ins.add(i); i = LIST_TOKEN_RE.lastIndex; continue; }
    }
    i += 1;
  }
  let out = "";
  for (let k = 0; k < n; k++) out += (ins.has(k) ? "\\" : "") + s[k];
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

/* The prompt box's own tint (owner walk 2026-09-29; Power Tools Handoff M1: "{a|b|c} and
   __name__ are tinted lavender in the prompt"): the RAW text cut into runs that join back to
   it character for character -- a variable "var", a refusal "bad" (peach), everything else ""
   -- for the highlight layer the dock draws under its textarea. A brace group with no | is
   literal text, so {masterpiece} never tints; an escaped group stays plain too. */
export function promptTint(template, lists) {
  const s = String(template == null ? "" : template);
  const out = [];
  let at = 0;
  for (const p of parse(s, lists).parts) {
    if (!p.at) continue;
    const [a, b] = p.at;
    if (a > at) out.push({ t: s.slice(at, a), kind: "" });
    out.push({ t: s.slice(a, b), kind: p.var != null ? "var" : "bad" });
    at = b;
  }
  if (at < s.length) out.push({ t: s.slice(at), kind: "" });
  return out;
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
     event: {type: "get404" | "get" | "getFailed" | "post" | "postLost", run?, at}
   - a 404 while the POST is out means "not received yet" -- keep waiting;
   - a run from either answer that is terminal ends it ("done");
   - a lost POST (transport error) turns to reading back; a 404 that lasts READBACK_LOST_MS
     after that is "lost": "may not have reached the server", never "not sent";
   - a read that FAILED (a transport error, a 5xx, a store that couldn't be read: getFailed)
     counts toward the same window, from the last read that answered (review N8) -- so a
     server that stopped answering never leaves Send disabled until a reload. After a run was
     seen it ends "lost" with that run (LOST_SEEN_WORDS), never as "not sent".
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
      return { ...s, run, okAt: at };
    }
    case "get404":
      if (s.phase === "reading" && !s.run && at - s.since >= READBACK_LOST_MS) {
        return { phase: "lost", since: at, run: null };
      }
      return s;
    case "getFailed": {
      const from = Math.max(Number(s.since) || 0, Number(s.okAt) || 0);
      if (s.phase === "reading" && at - from >= READBACK_LOST_MS) {
        return { phase: "lost", since: at, run: s.run || null };
      }
      return s;
    }
    default:
      return s;
  }
}

/* An apiGet answer from GET /api/generate/runs/<id> as a readBack event: a 404, a run, or a
   read that failed (anything else: api.js's "network error: ..." body, a 5xx, the server's
   "Couldn't read the run."). */
export function readBackEvent(d, at) {
  if (d && d.http_status === 404) return { type: "get404", at };
  if (d && !d.error) return { type: "get", run: d, at };
  return { type: "getFailed", at };
}

export const LOST_WORDS = "This run may not have reached the server — check the Activity tray before sending again.";
export const LOST_SEEN_WORDS = "Lost touch with the server while this run was being sent — check the Activity tray before sending again.";

/* The run's idempotency key: a uuid4 as 32 hex characters, drawn once per confirm (the
   server's _RUN_ID_RE). Pure but for the random source. */
export function newRunId() {
  const c = (typeof crypto !== "undefined" && crypto) || null;
  const bytes = new Uint8Array(16);
  if (c && c.getRandomValues) c.getRandomValues(bytes);
  else for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;         // uuid4
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

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

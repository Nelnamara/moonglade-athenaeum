/* THE COLOUR PALETTE'S PURE CORE -- the Generate drawer's palette (Session H decision 4,
   Tsubaki3 Generate Handoff.dc.html frame D, and the Library tab built to PixAI's own
   pattern, reference shots 23-25). Not the COMMAND palette: that one is palette/paletteCore.js.

   Everything that can be decided without React lives here -- the editor's state moves (turn
   a group on or off, seed even shares, drag a divider, step a share, reorder, remove, change
   the colour count), validation, the request shape, the preview card's colours, the saved
   ("mine") list, and the colour extraction behind "Extract from image" -- so
   loom/test/color-palette-core.test.js pins it with no DOM.

   THE SHAPE IS PIXAI'S. A palette is {overall?, background?, character?}, each group
   {colors: [{hex: "#RRGGBB", ratio: 0-100}]} with 1-12 colours, and overall or background
   must be present (the contract's color-palette schema). A generation carries
   colorPalette: {name, palette} (the task-parameter schema). The editor keeps every group's
   colours even while the group is OFF (held, like the drawer's other held fields); only the
   groups that are ON reach toPalette().

   SHARES. Every group the editor builds sums to exactly 100, in whole percents, each colour at
   least 1. Every move below preserves that sum: a divider or a stepper trades share with ONE
   neighbour, a removed colour's share goes to one neighbour, and a count change re-evens.

   Editor state:
     { name, id, from, on: {overall, background, character},
       groups: {overall: [{hex, ratio}], ...}, focus: {group, index} }
   `id` is the saved palette's id ("" until it is saved as mine), `from` the Library palette it
   started from ("" for a blank one). Every function returns a NEW state; none mutates. */

export const GROUPS = ["overall", "background", "character"];
export const GROUP_LABEL = { overall: "Overall", background: "Background", character: "Character" };
export const MIN_COLORS = 1;
export const MAX_COLORS = 12;
export const SEED_COUNT = 6;
export const NAME_MAX = 50;
export const MINE_MAX = 30;
export const MINE_KEY = "palette.mine";
export const UNTITLED = "Untitled colour palette";
export const HEX_RE = /^#[0-9a-fA-F]{6}$/;

/* The colours a group is seeded with when it is turned on empty, or when the count grows past
   what it holds -- PixAI's own seed is a lavender ramp (reference 25); this continues it. */
export const SEED = [
  "#F2ECFB", "#E3D4F7", "#C9AEF0", "#A97FE6", "#8C5AD8", "#6E35C2",
  "#4F2A94", "#D6E4F7", "#9DB8E3", "#6A89C9", "#F7D9E3", "#E3A3BC",
];

/* n whole percents summing to 100, the remainder on the first ones: 6 -> 17,17,17,17,16,16. */
export function evenShares(n) {
  const k = Math.max(0, Math.floor(n));
  if (!k) return [];
  const base = Math.floor(100 / k);
  const rem = 100 - base * k;
  return Array.from({ length: k }, (_, i) => base + (i < rem ? 1 : 0));
}

/* Integer percents from any non-negative weights: largest remainder to a sum of 100, then
   each raised to at least 1 (taken from the largest). Whole percents that already sum to 100
   come back unchanged -- a Library palette's own 30/20/15/15/10/10 is kept exactly. */
export function toPercents(weights) {
  const w = (weights || []).map((x) => (Number.isFinite(+x) && +x > 0 ? +x : 0));
  const n = w.length;
  if (!n) return [];
  const total = w.reduce((a, b) => a + b, 0);
  if (!total) return evenShares(n);
  const raw = w.map((x) => (x / total) * 100);
  const out = raw.map((x) => Math.floor(x));
  let left = 100 - out.reduce((a, b) => a + b, 0);
  const order = raw.map((x, i) => [x - Math.floor(x), i]).sort((a, b) => b[0] - a[0] || a[1] - b[1]);
  for (let j = 0; left > 0; j = (j + 1) % n, left--) out[order[j][1]] += 1;
  for (let i = 0; i < n; i++) {
    while (out[i] < 1) {
      let big = 0;
      for (let k = 1; k < n; k++) if (out[k] > out[big]) big = k;
      if (out[big] <= 1) break;                      // more than 100 colours: cannot happen (<= 12)
      out[big] -= 1;
      out[i] += 1;
    }
  }
  return out;
}

export const normHex = (h) => String(h || "").trim().toUpperCase();
export const isHex = (h) => HEX_RE.test(String(h || "").trim());

const _copyGroups = (g) => ({
  overall: (g.overall || []).map((c) => ({ hex: c.hex, ratio: c.ratio })),
  background: (g.background || []).map((c) => ({ hex: c.hex, ratio: c.ratio })),
  character: (g.character || []).map((c) => ({ hex: c.hex, ratio: c.ratio })),
});
const _with = (ed, patch) => ({ ...ed, ...patch });
const _setGroup = (ed, k, list) => _with(ed, { groups: { ..._copyGroups(ed.groups), [k]: list } });

/* The seeded colours for a group of n, skipping hexes it already holds. */
function _seed(n, taken) {
  const have = new Set((taken || []).map(normHex));
  const out = [];
  for (const h of SEED) {
    if (out.length >= n) break;
    if (!have.has(h)) { out.push(h); have.add(h); }
  }
  for (let i = 0; out.length < n; i++) out.push(SEED[i % SEED.length]);
  return out;
}

const _even = (hexes) => {
  const sh = evenShares(hexes.length);
  return hexes.map((h, i) => ({ hex: normHex(h), ratio: sh[i] }));
};

/* A blank palette: overall on with six even seed colours, the other two off and empty --
   PixAI's own "New color palette" opens on Overall with six (reference 25). */
export function newEditor(name) {
  return {
    name: String(name || UNTITLED).slice(0, NAME_MAX),
    id: "", from: "",
    on: { overall: true, background: false, character: false },
    groups: { overall: _even(_seed(SEED_COUNT)), background: [], character: [] },
    focus: { group: "overall", index: 0 },
  };
}

/* A colour list off any palette group ({colors:[...]}), cleaned: valid hexes only, at most
   12, shares made whole percents summing to 100. */
export function cleanColors(group) {
  const raw = (group && Array.isArray(group.colors)) ? group.colors : [];
  const ok = raw.filter((c) => c && isHex(c.hex)).slice(0, MAX_COLORS);
  const pct = toPercents(ok.map((c) => c.ratio));
  return ok.map((c, i) => ({ hex: normHex(c.hex), ratio: pct[i] }));
}

/* An editor opened on an existing palette (a Library preset to customise, or a saved one). */
export function editorFromPalette(palette, opts) {
  const o = opts || {};
  const p = palette || {};
  const groups = { overall: cleanColors(p.overall), background: cleanColors(p.background),
    character: cleanColors(p.character) };
  const on = { overall: groups.overall.length > 0, background: groups.background.length > 0,
    character: groups.character.length > 0 };
  if (!on.overall && !on.background) {                 // not a valid palette: start from blank
    const blank = newEditor(o.name);
    return { ...blank, id: o.id || "", from: o.from || "" };
  }
  const first = GROUPS.find((k) => on[k]);
  return {
    name: String(o.name || UNTITLED).slice(0, NAME_MAX),
    id: o.id || "", from: o.from || "",
    on, groups, focus: { group: first, index: 0 },
  };
}

/* Turning a group off would leave neither overall nor background on: the toggle is locked. */
export function groupLocked(ed, k) {
  if (!ed.on[k]) return false;
  if (k === "overall") return !ed.on.background;
  if (k === "background") return !ed.on.overall;
  return false;
}

/* The group's on/off switch. Turning one on that holds no colours seeds six even ones; its
   held colours come back as they were otherwise. Turning off the focused group moves the
   focus to overall (or background). A locked toggle returns the same state. */
export function toggleGroup(ed, k) {
  if (GROUPS.indexOf(k) < 0 || groupLocked(ed, k)) return ed;
  const on = { ...ed.on, [k]: !ed.on[k] };
  let next = _with(ed, { on });
  if (on[k]) {
    if (!ed.groups[k].length) next = _setGroup(next, k, _even(_seed(SEED_COUNT)));
    next = _with(next, { focus: { group: k, index: 0 } });
  } else if (ed.focus.group === k) {
    next = _with(next, { focus: { group: on.overall ? "overall" : "background", index: 0 } });
  }
  return next;
}

export function focusBand(ed, k, i) {
  if (!ed.on[k]) return ed;
  const n = ed.groups[k].length;
  return _with(ed, { focus: { group: k, index: Math.max(0, Math.min(n - 1, i | 0)) } });
}

/* The colour-count stepper: 1-12, keeps the colours it has (the first n), fills from the seed,
   and re-evens every share (PixAI's own stepper does). */
export function setCount(ed, k, n) {
  if (!ed.on[k]) return ed;
  const cur = ed.groups[k];
  const want = Math.max(MIN_COLORS, Math.min(MAX_COLORS, n | 0));
  if (want === cur.length) return ed;
  const keep = cur.slice(0, want).map((c) => c.hex);
  const hexes = keep.concat(_seed(want - keep.length, keep));
  const next = _setGroup(ed, k, _even(hexes));
  return ed.focus.group === k
    ? _with(next, { focus: { group: k, index: Math.min(ed.focus.index, want - 1) } })
    : next;
}

/* The neighbour a colour trades share with: the next one, or the previous one for the last. */
export const tradePartner = (n, i) => (i < n - 1 ? i + 1 : i - 1);

/* − share % + on a row: +1 takes one from the neighbour, −1 gives one; neither drops below 1. */
export function stepShare(ed, k, i, delta) {
  const list = ed.groups[k];
  const n = list.length;
  if (!ed.on[k] || n < 2 || i < 0 || i >= n) return ed;
  const j = tradePartner(n, i);
  const d = delta > 0 ? Math.min(delta | 0 || 1, list[j].ratio - 1)
    : -Math.min(Math.abs(delta | 0) || 1, list[i].ratio - 1);
  if (!d) return ed;
  const out = list.map((c) => ({ ...c }));
  out[i].ratio += d;
  out[j].ratio -= d;
  return _setGroup(ed, k, out);
}

/* A divider between colour i and i+1, dragged: colour i takes `left` percent of the pair's
   combined share and i+1 keeps the rest, both at least 1. */
export function setDivider(ed, k, i, left) {
  const list = ed.groups[k];
  if (!ed.on[k] || i < 0 || i >= list.length - 1) return ed;
  const pair = list[i].ratio + list[i + 1].ratio;
  const a = Math.max(1, Math.min(pair - 1, Math.round(Number(left) || 0)));
  if (a === list[i].ratio) return ed;
  const out = list.map((c) => ({ ...c }));
  out[i].ratio = a;
  out[i + 1].ratio = pair - a;
  return _setGroup(ed, k, out);
}

/* The divider's new share from a pointer position: `frac` is where the pointer sits across
   the WHOLE bar (0-1); the colours left of the pair keep their share, so the pair's left
   colour takes (frac*100 - share before it). Rounded; setDivider clamps it. */
export function dividerShareAt(list, i, frac) {
  const before = list.slice(0, i).reduce((a, c) => a + c.ratio, 0);
  return Math.round(Math.max(0, Math.min(1, Number(frac) || 0)) * 100) - before;
}

/* ↑ ↓: swap with the colour before or after; the focus follows the moved colour. */
export function moveColor(ed, k, i, dir) {
  const list = ed.groups[k];
  const j = i + (dir < 0 ? -1 : 1);
  if (!ed.on[k] || i < 0 || i >= list.length || j < 0 || j >= list.length) return ed;
  const out = list.map((c) => ({ ...c }));
  [out[i], out[j]] = [out[j], out[i]];
  const next = _setGroup(ed, k, out);
  return ed.focus.group === k && ed.focus.index === i
    ? _with(next, { focus: { group: k, index: j } }) : next;
}

/* × on a row: the colour goes and its share joins the one before it (or after, for the
   first). The last colour of a group cannot be removed -- turn the group off instead. */
export function removeColor(ed, k, i) {
  const list = ed.groups[k];
  if (!ed.on[k] || list.length <= MIN_COLORS || i < 0 || i >= list.length) return ed;
  const out = list.map((c) => ({ ...c }));
  const gone = out.splice(i, 1)[0];
  out[i > 0 ? i - 1 : 0].ratio += gone.ratio;
  const next = _setGroup(ed, k, out);
  if (ed.focus.group !== k) return next;
  const idx = ed.focus.index > i ? ed.focus.index - 1 : Math.min(ed.focus.index, out.length - 1);
  return _with(next, { focus: { group: k, index: idx } });
}

export function setHex(ed, k, i, hex) {
  const list = ed.groups[k];
  if (!isHex(hex) || i < 0 || i >= list.length) return ed;
  const out = list.map((c) => ({ ...c }));
  out[i].hex = normHex(hex);
  return _setGroup(ed, k, out);
}

export const rename = (ed, name) => _with(ed, { name: String(name == null ? "" : name).slice(0, NAME_MAX) });

/* "Replace colours from the Library": every group takes the Library palette's colours and
   on/off state; the name and the saved id are kept (it is still this palette). */
export function replaceFromLibrary(ed, preset) {
  const fresh = editorFromPalette(preset && preset.palette, { name: ed.name, id: ed.id });
  return { ...fresh, name: ed.name, id: ed.id, from: (preset && preset.name) || ed.from };
}

/* "Extract from image": the group being edited takes the image's colours and shares, and is
   turned on. `colors` is extractColors()'s answer. */
export function fillGroup(ed, k, colors) {
  const list = (colors || []).filter((c) => c && isHex(c.hex)).slice(0, MAX_COLORS);
  if (!list.length || GROUPS.indexOf(k) < 0) return ed;
  const pct = toPercents(list.map((c) => c.ratio));
  const next = _setGroup(ed, k, list.map((c, i) => ({ hex: normHex(c.hex), ratio: pct[i] })));
  return _with(next, { on: { ...ed.on, [k]: true }, focus: { group: k, index: 0 } });
}

export const groupTotal = (list) => (list || []).reduce((a, c) => a + (Number(c.ratio) || 0), 0);

/* Plain sentences for what stops a save; [] when it can be saved and applied. */
export function validate(ed) {
  const out = [];
  if (!String(ed.name || "").trim()) out.push("Give the palette a name");
  if (!ed.on.overall && !ed.on.background) out.push("Turn on overall or background");
  for (const k of GROUPS) {
    if (!ed.on[k]) continue;
    const list = ed.groups[k];
    if (list.length < MIN_COLORS || list.length > MAX_COLORS) {
      out.push(GROUP_LABEL[k] + " needs 1 to 12 colours");
    } else if (list.some((c) => !isHex(c.hex))) {
      out.push(GROUP_LABEL[k] + " has a colour that isn't a #RRGGBB hex");
    } else if (groupTotal(list) !== 100) {
      out.push(GROUP_LABEL[k] + "'s shares add to " + groupTotal(list) + "%, not 100%");
    }
  }
  return out;
}

/* The palette as PixAI takes it: only the groups that are on. */
export function toPalette(ed) {
  const out = {};
  for (const k of GROUPS) {
    if (ed.on[k] && ed.groups[k].length) {
      out[k] = { colors: ed.groups[k].map((c) => ({ hex: normHex(c.hex), ratio: c.ratio })) };
    }
  }
  return out;
}

/* ---- the applied palette (drawer state `s.palette`) and the request ----------------------

   s.palette = {name, palette, source: "library" | "mine", id, from} or null.

   paletteForPayload decides whether the request carries it: a palette is applied, the picked
   version takes one (`color_palette === true`, which the server sets only when PixAI's
   /features lists colorPalette "on"), and no context image is in play (`ctx`). Anything else
   -> null, and buildPayload leaves the key out entirely. The pick itself is never cleared by
   this -- it is HELD (the drawer's rule for what does not apply). */
export function paletteForPayload(s, ctx) {
  const pal = s && s.palette;
  if (!pal || !pal.palette) return null;
  if (!(s.model && s.model.color_palette === true)) return null;
  if (ctx) return null;
  const p = pal.palette;
  if (!(p.overall || p.background)) return null;
  return { name: String(pal.name || UNTITLED).slice(0, NAME_MAX), palette: p };
}

/* What the PALETTE row says about the applied palette. `ctx`: context images are on. */
export function paletteRowState(s, ctx) {
  const pal = s && s.palette;
  if (!pal) return { state: "none", note: "" };
  if (ctx) return { state: "held", note: "Held · not sent with context images" };
  if (s.model && s.model.color_palette === false) {
    return { state: "held", note: "Held · this model takes no colour palette" };
  }
  if (!(s.model && s.model.color_palette === true)) {
    const note = !s.model ? "Held · pick a model"
      : s.model.resolving ? "Held · checking this model"
        : "Held · couldn't confirm this model takes a colour palette";
    return { state: "held", note };
  }
  return { state: "on", note: "" };
}

/* "My Nightglade · overall + background" */
export function paletteSummary(pal) {
  if (!pal || !pal.palette) return "";
  const groups = GROUPS.filter((k) => pal.palette[k] && (pal.palette[k].colors || []).length);
  return (pal.name || UNTITLED) + (groups.length ? " · " + groups.join(" + ") : "");
}

/* The colours a card's strip shows: overall, else background. */
export function stripOf(palette) {
  const p = palette || {};
  const o = (p.overall && p.overall.colors) || [];
  return o.length ? o : ((p.background && p.background.colors) || []);
}

/* The live preview card (frame D, 4c): background as the field, character (or overall) as
   the figure, overall as the strip. The same formulas the handoff's own card uses. */
export function previewOf(palette) {
  const p = palette || {};
  const ov = (p.overall && p.overall.colors) || [];
  const bg = (p.background && p.background.colors) || [];
  const ch = (p.character && p.character.colors) || [];
  const field = (bg[0] || ov[ov.length - 1] || { hex: "#2A3A5A" }).hex;
  const figure = (ch[0] || ov[0] || bg[1] || { hex: "#8A8FB8" }).hex;
  return { field, figure, strip: ov.length ? ov : bg };
}

/* Legible ink on a colour: dark on light bands, light on dark (the handoff's lum() > .6). */
export function inkOn(hex) {
  const n = parseInt(String(hex || "").slice(1), 16);
  if (!Number.isFinite(n)) return "light";
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6 ? "dark" : "light";
}

/* ---- the Library (GET /api/palettes/presets) --------------------------------------------- */

/* Does a raw palette hold usable overall or background colours (PixAI's one hard rule)? */
export function hasBase(palette) {
  const p = palette || {};
  return cleanColors(p.overall).length > 0 || cleanColors(p.background).length > 0;
}

/* One preset from the server, cleaned; null when it holds no usable palette. */
export function normalizePreset(raw) {
  if (!raw || typeof raw !== "object" || !hasBase(raw.palette)) return null;
  const ed = editorFromPalette(raw.palette, {});
  return {
    id: String(raw.id || ""),
    name: String(raw.name || "").slice(0, NAME_MAX) || "Palette",
    cover_url: typeof raw.cover_url === "string" ? raw.cover_url : "",
    palette: toPalette(ed),
  };
}

/* ---- "mine": the account's saved palettes (useAccountPrefs, MINE_KEY) --------------------- */

export function normalizeMine(raw) {
  if (!Array.isArray(raw)) return [];
  const out = [];
  const seen = new Set();
  for (const e of raw) {
    if (!e || typeof e !== "object" || !e.id || seen.has(e.id) || !hasBase(e.palette)) continue;
    const pal = toPalette(editorFromPalette(e.palette, {}));
    seen.add(e.id);
    out.push({ id: String(e.id), name: String(e.name || UNTITLED).slice(0, NAME_MAX),
      palette: pal, from: String(e.from || "") });
    if (out.length >= MINE_MAX) break;
  }
  return out;
}

export function newMineId(now, rnd) {
  const t = Math.floor(Number(now) || 0).toString(36);
  const r = Math.floor((Number(rnd) || 0) * 1e6).toString(36);
  return "m" + t + r;
}

/* Save an editor as mine: replaces the entry with the same id, else goes first. The list is
   capped at MINE_MAX -- `full` says a new one would pass it (the caller refuses; nothing is
   dropped silently). Returns {list, entry, full}. */
export function upsertMine(list, ed, id) {
  const cur = normalizeMine(list);
  const entry = { id: ed.id || id, name: String(ed.name || UNTITLED).trim().slice(0, NAME_MAX) || UNTITLED,
    palette: toPalette(ed), from: ed.from || "" };
  const at = cur.findIndex((e) => e.id === entry.id);
  if (at >= 0) {
    const next = cur.slice();
    next[at] = entry;
    return { list: next, entry, full: false };
  }
  if (cur.length >= MINE_MAX) return { list: cur, entry, full: true };
  return { list: [entry].concat(cur), entry, full: false };
}

export const removeMine = (list, id) => normalizeMine(list).filter((e) => e.id !== id);

/* ---- "Extract from image" ----------------------------------------------------------------

   Median cut over an RGBA pixel buffer (a canvas getImageData of a downscaled picture):
   repeatedly split the box with the widest channel range at its median until there are
   `count` boxes, then each box is its mean colour with its pixel count as the weight.
   Deterministic, so the same picture always gives the same palette. Pixels under half alpha
   are skipped. Returns [{hex, ratio}] sorted by share, ratios whole percents summing to 100;
   fewer than `count` when the picture holds fewer distinct colours. */
export function extractColors(data, count) {
  const want = Math.max(1, Math.min(MAX_COLORS, count | 0 || SEED_COUNT));
  const px = [];
  for (let i = 0; i + 3 < (data ? data.length : 0); i += 4) {
    if (data[i + 3] < 128) continue;
    px.push([data[i], data[i + 1], data[i + 2]]);
  }
  if (!px.length) return [];
  const range = (box) => {
    let best = -1, ch = 0;
    for (let c = 0; c < 3; c++) {
      let lo = 255, hi = 0;
      for (const p of box) { if (p[c] < lo) lo = p[c]; if (p[c] > hi) hi = p[c]; }
      if (hi - lo > best) { best = hi - lo; ch = c; }
    }
    return [best, ch];
  };
  let boxes = [px];
  while (boxes.length < want) {
    let pick = -1, pickRange = 0, pickCh = 0;
    boxes.forEach((b, i) => {
      if (b.length < 2) return;
      const [r, c] = range(b);
      if (r > pickRange) { pickRange = r; pick = i; pickCh = c; }
    });
    if (pick < 0) break;                               // every box is one flat colour
    const box = boxes[pick].slice().sort((a, b) => a[pickCh] - b[pickCh] || a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
    const mid = box.length >> 1;
    boxes = boxes.slice(0, pick).concat([box.slice(0, mid), box.slice(mid)], boxes.slice(pick + 1));
  }
  const hex2 = (v) => Math.round(v).toString(16).padStart(2, "0").toUpperCase();
  const merged = new Map();
  for (const b of boxes) {
    const sum = [0, 0, 0];
    for (const p of b) { sum[0] += p[0]; sum[1] += p[1]; sum[2] += p[2]; }
    const hex = "#" + hex2(sum[0] / b.length) + hex2(sum[1] / b.length) + hex2(sum[2] / b.length);
    merged.set(hex, (merged.get(hex) || 0) + b.length);
  }
  const rows = [...merged.entries()].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1));
  const pct = toPercents(rows.map((r) => r[1]));
  return rows.map((r, i) => ({ hex: r[0], ratio: pct[i] }));
}

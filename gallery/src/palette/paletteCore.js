/* The command palette's PURE core -- fuzzy match, in-group ranking, group folding, the
   Recent ledger. Same split as picker/pickerCore.js and gen/genCore.js: everything that
   can be decided without React lives here, so the behaviour is readable in one place and
   testable without a DOM.

   Locked source: design/command-palette/Command Palette.dc.html (moonglade-internal),
   frames A-H. Its own `hl()` is the matcher this file reproduces -- a plain SUBSEQUENCE
   scan, left to right, case-insensitive, run-length-collapsed into {text, hit} parts. Not
   a scorer-with-bonuses: the DC prints "matches land anywhere in a label" and nothing
   more, and a power tool whose ordering nobody can predict is worse than a dumb one. */

/* Split `label` into consecutive {t, hit} runs against query `q`, exactly the way the
   DC's hl() does: walk the label once, advance the query cursor on every character that
   matches the next query character, and start a new run whenever hit-ness flips.
   A blank query returns the whole label as one non-hit run. */
export function highlight(label, q) {
  const text = String(label == null ? "" : label);
  if (!q) return [{ t: text, hit: false }];
  const ql = String(q).toLowerCase();
  let qi = 0;
  const out = [];
  let buf = "";
  let hitBuf = null;
  for (const ch of text) {
    const hit = qi < ql.length && ch.toLowerCase() === ql[qi];
    if (hit) qi++;
    if (hitBuf === null || hit !== hitBuf) {
      if (buf) out.push({ t: buf, hit: hitBuf });
      buf = ch;
      hitBuf = hit;
    } else {
      buf += ch;
    }
  }
  if (buf) out.push({ t: buf, hit: hitBuf });
  return out;
}

/* Does `label` contain `q` as a subsequence, and how good is the match?
   Returns null for a miss, else a score where LOWER is better:

     firstIndex * 2   how late the match starts ("st" prefers Storyboard over Toggle Stack)
     + spread         how scattered it is (0 when the run is contiguous)

   Deterministic, no tie-break randomness, no per-character bonus table. Ties keep their
   declaration order because the sort below is stable. */
export function matchScore(label, q) {
  if (!q) return 0;
  const s = String(label == null ? "" : label).toLowerCase();
  const ql = String(q).toLowerCase();
  let qi = 0;
  let first = -1;
  let last = -1;
  for (let i = 0; i < s.length && qi < ql.length; i++) {
    if (s[i] !== ql[qi]) continue;
    if (first < 0) first = i;
    last = i;
    qi++;
  }
  if (qi < ql.length) return null;
  const spread = last - first - (ql.length - 1);
  return first * 2 + spread;
}

/* Fold a flat command list into the palette's rendered groups.

   Group ORDER is fixed and never re-ranks (DC §8.4): the order groups first appear in
   `commands` is the order they render in, filtered or not. Only rows re-rank, and only
   inside their own group. A group with zero matches drops away entirely, header included.

   Each returned row carries its own `index` -- the flat keyboard position across every
   group -- so the up/down handler never has to re-walk the tree. */
export function groupCommands(commands, q) {
  const query = String(q || "").trim();
  const order = [];
  const bucket = new Map();
  for (const c of commands || []) {
    if (!bucket.has(c.group)) {
      bucket.set(c.group, []);
      order.push(c.group);
    }
    const score = matchScore(c.label, query);
    if (score === null) continue;
    bucket.get(c.group).push({ cmd: c, score });
  }
  const groups = [];
  let index = 0;
  for (const name of order) {
    const rows = bucket.get(name);
    if (!rows.length) continue;                       // zero-match group drops away
    if (query) rows.sort((a, b) => a.score - b.score); // stable: ties keep declaration order
    groups.push({
      name,
      extra: rows[0].cmd.groupExtra || "",
      rows: rows.map((r) => ({
        cmd: r.cmd,
        parts: highlight(r.cmd.label, query),
        index: index++,
      })),
    });
  }
  return { groups, count: index };
}

/* ---- the Recent ledger (DC §8.1: the last 3 RUN commands, most recent first) ----

   localStorage, matching every other lightweight per-user gallery preference in this app
   (mg_gallery_layout / mg_gallery_group / mg_gallery_density / mg_banner_slim /
   gallery_privacy_blur / mg-pk-tile). There is no server-side UI-preference route to use
   instead -- /api/panel/schedule is a server behaviour and /api/skin is achievement state,
   neither is a per-browser view setting -- so localStorage IS the house pattern here, and
   a command id is worth exactly as much as the browser it was pressed in.

   Guarded like the rest of them: a private-mode throw costs the Recent group, nothing else. */
export const RECENT_KEY = "mg_palette_recent";
export const RECENT_MAX = 3;

export function readRecent() {
  try {
    const raw = window.localStorage.getItem(RECENT_KEY);
    if (!raw) return [];
    const list = JSON.parse(raw);
    return Array.isArray(list) ? list.filter((x) => typeof x === "string").slice(0, RECENT_MAX) : [];
  } catch {
    return [];                                        // private mode / corrupt value: no Recent group
  }
}

/* Most recent first, de-duplicated, capped at three. Returns the new list so the caller
   can set state off the same value it just wrote. */
export function pushRecent(id, current) {
  const next = [id].concat((current || []).filter((x) => x !== id)).slice(0, RECENT_MAX);
  try {
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch { /* private mode -- the list just doesn't survive the reload */ }
  return next;
}

/* The DC's Copy-id sub: `a91f…c04d`. Short ids stay whole rather than growing an ellipsis. */
export function shortId(mid) {
  const s = String(mid == null ? "" : mid);
  return s.length <= 10 ? s : s.slice(0, 4) + "…" + s.slice(-4);
}

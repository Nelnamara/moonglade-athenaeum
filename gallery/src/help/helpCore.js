/* THE GUIDE'S PURE CORE (Session I, 2026-09-28 -- ../moonglade-internal/design/
   handoff-2026-09-04/Help and First Run Handoff.dc.html, section B; decisions in
   design/notes/help-first-run/NOTES.md).

   Help renders the wiki/ shipped with this install (GET /api/help/page/<slug> hands a page
   over as markdown TEXT). This file turns that text into plain data -- blocks and spans --
   and the overlay renders the data through React, so every character of the page lands in a
   text child and is escaped by construction. There is no HTML string and no
   dangerouslySetInnerHTML anywhere on this road, for the same reason lib/markdownLite.js
   gives: a sanitizer is a thing that can be wrong, and React's escaping cannot be.

   markdownLite.js is the contest brief's renderer and deliberately tiny; the wiki needs
   more (fenced code, tables, block quotes, inline code, nested emphasis inside links,
   heading anchors that match GitHub's), so the wiki gets its own parser here rather than
   growing that one past what a contest brief can ever send.

   Also here, because each is a decision and none needs a DOM: link classification (a wiki
   link opens in place, an outside link gets ↗), the Glossary's underlines (first use of a
   term on a page, never inside code, links or headings), the page search (titles and
   headings, the palette's own subsequence matcher), which page each surface's "?" opens,
   and the what's-new plan (toast, sheet or About; once per version per account).

   Imports only the palette's pure matcher, so loom/test/help-core.test.js drives all of it
   under node --test. */

import { matchScore } from "../palette/paletteCore.js";

/* ============================== anchors ============================== */

/* The anchor GitHub gives a heading -- lowercase, everything but letters, digits, `_`,
   `-` and spaces dropped, spaces to hyphens, and -1/-2... on a repeat within one page -- so
   a `Page#anchor` link written for the online wiki lands on the same heading here. The
   server sends heading TEXT only, so this is the one place an anchor is made; a node test
   walks every `#anchor` link in the shipped wiki against it. */
export function githubSlug(text, used) {
  let s = plainInline(text).toLowerCase()
    .replace(/[^\p{L}\p{M}\p{N}_\- ]/gu, "")
    .replace(/ /g, "-");
  if (used) {
    const base = s;
    let n = 0;
    while (used.has(s)) { n += 1; s = base + "-" + n; }
    used.add(s);
  }
  return s;
}

/* ============================== inline ============================== */

// One scan, earliest match first; the alternation order settles a tie at the same index:
// code (its contents are literal), a link (its label may itself hold code or bold), bold,
// then italic. `_word_` italics need a non-word character on both sides, so snake_case in
// prose stays prose.
const INLINE = /`([^`\n]+)`|\[([^\]\n]+)\]\(([^()\s]+)\)|\*\*(.+?)\*\*|\*([^*\s][^*\n]*?)\*|(?<![\p{L}\p{N}_])_([^_\n]+)_(?![\p{L}\p{N}_])/gu;

export function parseInline(text) {
  const src = String(text == null ? "" : text);
  const out = [];
  const push = (v) => {
    if (!v) return;
    const last = out[out.length - 1];
    if (last && last.t === "text") last.v += v;
    else out.push({ t: "text", v });
  };
  let at = 0;
  const re = new RegExp(INLINE.source, INLINE.flags);
  let m;
  while ((m = re.exec(src)) !== null) {
    push(src.slice(at, m.index));
    at = re.lastIndex;
    if (m[1] != null) out.push({ t: "code", v: m[1] });
    else if (m[2] != null) out.push({ t: "a", href: m[3], c: parseInline(m[2]) });
    else if (m[4] != null) out.push({ t: "b", c: parseInline(m[4]) });
    else if (m[5] != null) out.push({ t: "i", c: parseInline(m[5]) });
    else if (m[6] != null) out.push({ t: "i", c: parseInline(m[6]) });
  }
  push(src.slice(at));
  return out;
}

/* The words a reader sees, for titles, search and anchors. */
export function spansText(spans) {
  return (spans || []).map((s) => (s.c ? spansText(s.c) : s.t === "br" ? " " : s.v || "")).join("");
}
export function plainInline(text) {
  return spansText(parseInline(text)).replace(/\s+/g, " ").trim();
}

/* ============================== blocks ============================== */

const FENCE = /^\s*```/;
const HEADING = /^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$/;
const HR = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;
const BULLET = /^([ \t]*)[-*+][ \t]+(.*)$/;
const ORDERED = /^([ \t]*)(\d{1,9})[.)][ \t]+(.*)$/;
const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function tableCells(line) {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|") && !s.endsWith("\\|")) s = s.slice(0, -1);
  // A backslash-escaped pipe stays in its cell.
  return s.split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, "|"));
}

/* Markdown -> blocks:
     {type:"h", level, spans, text, anchor}
     {type:"p", spans}
     {type:"ul"|"ol", start?, items:[spans...]}
     {type:"code", text}
     {type:"quote", blocks:[...]}
     {type:"table", head:[spans...], align:["left"|"center"|"right"|""...], rows:[[spans...]...]}
     {type:"hr"}
   `used` collects heading anchors so repeats get GitHub's -1/-2 suffixes. */
export function parseWiki(md, used) {
  const lines = String(md == null ? "" : md).replace(/\r\n?/g, "\n").split("\n");
  const anchors = used || new Set();
  const blocks = [];
  let i = 0;
  const isBlank = (l) => !l || !l.trim();
  const startsBlock = (l) => FENCE.test(l) || HEADING.test(l) || HR.test(l)
    || /^\s*>/.test(l) || BULLET.test(l) || ORDERED.test(l) || /^\s*\|/.test(l);

  while (i < lines.length) {
    const line = lines[i];
    if (isBlank(line)) { i++; continue; }

    if (FENCE.test(line)) {
      const body = [];
      i++;
      while (i < lines.length && !FENCE.test(lines[i])) { body.push(lines[i]); i++; }
      i++;                                   // the closing fence (or the end of the page)
      blocks.push({ type: "code", text: body.join("\n") });
      continue;
    }

    const h = HEADING.exec(line);
    if (h) {
      const spans = parseInline(h[2]);
      const text = spansText(spans).replace(/\s+/g, " ").trim();
      blocks.push({ type: "h", level: h[1].length, spans, text, anchor: githubSlug(text, anchors) });
      i++;
      continue;
    }

    if (HR.test(line)) { blocks.push({ type: "hr" }); i++; continue; }

    if (/^\s*>/.test(line)) {
      const inner = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) {
        inner.push(lines[i].replace(/^\s*>\s?/, ""));
        i++;
      }
      blocks.push({ type: "quote", blocks: parseWiki(inner.join("\n"), anchors) });
      continue;
    }

    if (/^\s*\|/.test(line) && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
      const head = tableCells(line).map(parseInline);
      const align = tableCells(lines[i + 1]).map((c) => (
        /^:-+:$/.test(c) ? "center" : /^-+:$/.test(c) ? "right" : /^:-+$/.test(c) ? "left" : ""));
      i += 2;
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) {
        rows.push(tableCells(lines[i]).map(parseInline));
        i++;
      }
      blocks.push({ type: "table", head, align, rows });
      continue;
    }

    const b = BULLET.exec(line);
    const o = b ? null : ORDERED.exec(line);
    if (b || o) {
      const ordered = !!o;
      const items = [];
      let cur = null;
      while (i < lines.length) {
        const l = lines[i];
        const mb = BULLET.exec(l);
        const mo = mb ? null : ORDERED.exec(l);
        if ((ordered ? mo : mb) && !(ordered ? mo[1] : mb[1])) {
          cur = [ordered ? mo[3] : mb[2]];
          items.push(cur);
          i++;
          continue;
        }
        if (isBlank(l)) {
          // A blank line ends the list unless the next line carries on with another item.
          const next = lines[i + 1];
          if (next && (ordered ? ORDERED.test(next) : BULLET.test(next)) && !/^[ \t]/.test(next)) { i++; continue; }
          break;
        }
        if (cur && (/^[ \t]/.test(l) || !startsBlock(l))) {
          // An indented line (or a lazy continuation) belongs to the item above it;
          // an indented sub-bullet reads as its own line inside that item.
          const sub = BULLET.exec(l);
          cur.push(sub ? "\n• " + sub[2] : l.trim());
          i++;
          continue;
        }
        break;
      }
      blocks.push({
        type: ordered ? "ol" : "ul",
        ...(ordered ? { start: Number(o[2]) || 1 } : {}),
        items: items.map((parts) => {
          const spans = [];
          parts.join(" ").split("\n").forEach((seg, k) => {
            if (k) spans.push({ t: "br" });
            parseInline(seg.trim()).forEach((s) => spans.push(s));
          });
          return spans;
        }),
      });
      continue;
    }

    // A paragraph: consecutive lines until a blank one or the start of another block.
    const para = [line.trim()];
    i++;
    while (i < lines.length && !isBlank(lines[i]) && !startsBlock(lines[i])) {
      para.push(lines[i].trim());
      i++;
    }
    blocks.push({ type: "p", spans: parseInline(para.join(" ")) });
  }
  return blocks;
}

/* ============================== links ============================== */

const WIKI_WEB = /^https:\/\/github\.com\/Nelnamara\/moonglade-athenaeum\/wiki(?:\/([A-Za-z0-9][A-Za-z0-9_-]*))?\/?(?:#(.*))?$/;
const SLUG = /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/;

/* Where a link goes:
     {kind: "page", slug, anchor}   another page of the guide -- opens in place
     {kind: "anchor", anchor}       a heading on this page
     {kind: "external", href}       http(s) -- ↗, a new tab
     {kind: "text"}                 anything else (a relative repo path, a javascript: or
                                    data: target) renders as its own label, not a link */
export function classifyHref(href, slugs) {
  const h = String(href == null ? "" : href).trim();
  if (!h) return { kind: "text" };
  if (h.startsWith("#")) return { kind: "anchor", anchor: decodeURIComponent(h.slice(1)) };
  const web = WIKI_WEB.exec(h);
  if (web) return { kind: "page", slug: web[1] || "Home", anchor: web[2] ? decodeURIComponent(web[2]) : "" };
  if (/^https?:\/\//i.test(h)) return { kind: "external", href: h };
  const [slug, anchor] = h.split("#");
  if (SLUG.test(slug) && (!slugs || slugs.has(slug))) {
    return { kind: "page", slug, anchor: anchor ? decodeURIComponent(anchor) : "" };
  }
  return { kind: "text" };
}

/* ============================== the Glossary ============================== */

function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/* One matcher per Glossary term. A leading "the " is not part of what is underlined
   ("the dock" underlines "dock"); a term with a capital in it matches case-sensitively, so
   "Library" is the screen and "library" in a sentence is just a word; an all-lowercase term
   matches any case and a plural "s". Longest first, so "Live Mirror" wins over "Mirror". */
export function glossaryMatchers(terms) {
  return (terms || [])
    .map((t) => {
      const term = String(t.term || "").trim();
      const key = term.replace(/^the\s+/i, "").trim();
      if (key.length < 3) return null;
      const cased = /[A-Z]/.test(key);
      const body = escapeRe(key).replace(/\s+/g, "\\s+");
      const re = new RegExp("(?<![\\p{L}\\p{N}_-])(" + body + (cased ? "" : "s?") + ")(?![\\p{L}\\p{N}_-])",
        cased ? "u" : "iu");
      return { term, key, def: String(t.def || ""), re };
    })
    .filter(Boolean)
    .sort((a, b) => b.key.length - a.key.length);
}

/* Split the text spans of one block so the FIRST use of each term on the page becomes
   {t: "term", v, term, def}. Never inside code, a link's label or a heading (the caller
   simply does not hand headings in); `used` is the page's own record of what has been
   underlined already. Returns new spans; the input is not mutated. */
export function markGlossary(spans, matchers, used) {
  if (!matchers || !matchers.length) return spans;
  const walk = (list) => {
    const out = [];
    for (const s of list || []) {
      if (s.t === "text") out.push(...splitText(s.v));
      else if (s.t === "b" || s.t === "i") out.push({ ...s, c: walk(s.c) });
      else out.push(s);                     // code, links, breaks, terms: left alone
    }
    return out;
  };
  const splitText = (text) => {
    let best = null;
    for (const m of matchers) {
      if (used.has(m.key.toLowerCase())) continue;
      const hit = m.re.exec(text);
      if (hit && (!best || hit.index < best.index)) best = { m, index: hit.index, v: hit[1] };
    }
    if (!best) return text ? [{ t: "text", v: text }] : [];
    used.add(best.m.key.toLowerCase());
    const before = text.slice(0, best.index);
    const after = text.slice(best.index + best.v.length);
    return [
      ...(before ? [{ t: "text", v: before }] : []),
      { t: "term", v: best.v, term: best.m.term, def: best.m.def },
      ...splitText(after),
    ];
  };
  return walk(spans);
}

/* The whole page with its glossary underlines applied, block by block in reading order. */
export function markPage(blocks, matchers, used) {
  const seen = used || new Set();
  const inBlock = (b) => {
    if (b.type === "p") return { ...b, spans: markGlossary(b.spans, matchers, seen) };
    if (b.type === "ul" || b.type === "ol") return { ...b, items: b.items.map((it) => markGlossary(it, matchers, seen)) };
    if (b.type === "quote") return { ...b, blocks: b.blocks.map(inBlock) };
    if (b.type === "table") return { ...b, rows: b.rows.map((r) => r.map((c) => markGlossary(c, matchers, seen))) };
    return b;                                // headings, code, rules
  };
  return (blocks || []).map(inBlock);
}

/* ============================== search ============================== */

/* Fuzzy search over page titles and headings, with the palette's own subsequence matcher
   (DC B: "fuzzy matching as in the palette") so the two agree on what matches. Lower
   score is better; a title beats a heading on a tie, and the page list's own order breaks
   what is left. Returns [{slug, title, heading, level, score}]. */
export function searchGuide(pages, q, limit) {
  const query = String(q || "").trim();
  if (!query) return [];
  const hits = [];
  (pages || []).forEach((p, pi) => {
    const ts = matchScore(p.title, query);
    if (ts !== null) hits.push({ slug: p.slug, title: p.title, heading: "", level: 0, score: ts, pi, hi: -1 });
    (p.headings || []).forEach((h, hi) => {
      const hs = matchScore(h.text, query);
      if (hs !== null) hits.push({ slug: p.slug, title: p.title, heading: h.text, level: h.level, score: hs + 1, pi, hi });
    });
  });
  hits.sort((a, b) => a.score - b.score || a.pi - b.pi || a.hi - b.hi);
  return hits.slice(0, limit || 40).map(({ pi, hi, ...h }) => h);   // eslint-disable-line no-unused-vars
}

/* ============================== surfaces ============================== */

/* The page each surface's "?" (and the ? key on it) opens. Branding has no page of its own
   and must not be named anywhere public before its unlock, so its "?" opens the Control
   Panel's page, which is where the tab lives. */
export const SURFACE_PAGE = {
  gallery: "Gallery",
  dock: "Generating",
  loom: "The-Loom",
  folio: "Folio-of-Honors",
  panel: "Control-Panel",
  branding: "Control-Panel",
};
export const ABOUT_SLUG = "__about";

export function pageForSurface(surface) {
  return SURFACE_PAGE[surface] || "Home";
}

/* A page or heading that names Branding stays out of the list and the search until the
   tab is unlocked (DECISIONS 2026-07-26: no key, no hint). The shipped wiki has none; this
   is the rule for the day one is written. */
const HIDDEN_UNTIL_UNLOCK = /\bbranding\b/i;
export function visiblePages(pages, brandingUnlocked) {
  if (brandingUnlocked) return pages || [];
  return (pages || [])
    .filter((p) => !HIDDEN_UNTIL_UNLOCK.test(p.title) && !HIDDEN_UNTIL_UNLOCK.test(p.slug))
    .map((p) => ({ ...p, headings: (p.headings || []).filter((h) => !HIDDEN_UNTIL_UNLOCK.test(h.text)) }));
}

/* ============================== what's new ============================== */

/* What the first sign-in after an update does (decision 3). `seen` is the account's
   `seen.whatsnew` (undefined when it has never been written); `display` is the running
   version as the guide prints it (x.y, or x.y.z for a patch -- the server's
   display_version); `kind` is major | minor | patch; `hasLibrary` says the account has
   pictures, which is what separates an account that has been using the app from one that
   has only just been made.

     {show: false, mark: false}             already seen this version
     {show: false, mark: true}              a brand-new account: nothing to announce, but
                                            the version is noted so the NEXT one is news
     {show: true, mark: true, opens}        the toast, once; `opens` is "sheet" for a minor
                                            or major release, "about" for a patch */
export function whatsNewPlan({ seen, display, kind, hasLibrary }) {
  if (!display) return { show: false, mark: false };
  if (seen === display) return { show: false, mark: false };
  if (seen === undefined || seen === null || seen === "") {
    if (!hasLibrary) return { show: false, mark: true };
  }
  return { show: true, mark: true, opens: kind === "patch" ? "about" : "sheet" };
}

/* The sheet's four highlights: the entry's first four items, the block's own list before
   any "### Under the hood" section, topped up from those sections only if the list is
   short. */
export function highlightsOf(items, n) {
  const k = n || 4;
  const main = (items || []).filter((i) => !i.section);
  const rest = (items || []).filter((i) => i.section);
  return main.concat(rest).slice(0, k);
}

/* The toast's middle line: the release's own title when it has one, else its first lead. */
export function toastSummary(about) {
  if (!about) return "";
  return about.title || ((about.items || [])[0] || {}).lead || "";
}

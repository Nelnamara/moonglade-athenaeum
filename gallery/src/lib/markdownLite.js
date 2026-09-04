/* markdownLite -- the contest brief's renderer, and nothing more.

   PixAI serves a contest `description` as MARKDOWN. The JoJo Pose brief happens to be
   four plain paragraphs; others carry bold, headings and bullet lists. Rendering it as
   one flat string loses that, and rendering it with a markdown DEPENDENCY buys a parser,
   an HTML sink and a sanitizer to hold a handful of constructs.

   So: a pure function, string -> a plain-data BLOCK STRUCTURE. It does NOT emit HTML and
   there is no `dangerouslySetInnerHTML` anywhere downstream -- every character of upstream
   text lands in a React text child, which is escaped by construction. A `<script>` in the
   brief is a text span reading "<script>", never a node. That is the whole reason the
   output is a structure rather than a sanitized-HTML string: a sanitizer is a thing that
   can be wrong, and React's escaping cannot be.

   Supported, deliberately: paragraphs (blank-line separated; a single newline inside one
   becomes a `br` span), **bold**, *italic*, `#`/`##`/`###` headings, `-`/`*` bullets,
   `1.` ordered lists, and [text](https://url) links -- http/https ONLY, anything else
   renders as its own literal source text. Emphasis does not nest; a link's label is plain
   text. Everything else is text.

   Imports NOTHING, on purpose: the suite has no React render harness, so this module is
   driven directly by `loom/test/markdown-lite.test.js` under `node --test`, the same
   arrangement as hooks/contestSyncFlow.js.

   ---- the shapes ----
   block  = {type:"p",  spans:[...]}
          | {type:"h",  level:1|2|3, spans:[...]}
          | {type:"ul"|"ol", items:[ [span,...], ... ]}
   span   = {t:"text"|"b"|"i", v:string}
          | {t:"a", v:string, href:string}
          | {t:"br"}
*/

const HEADING = /^(#{1,3})[ \t]+(.+?)[ \t]*#*[ \t]*$/;
const BULLET = /^[ \t]*[-*][ \t]+(.+)$/;
const ORDERED = /^[ \t]*\d{1,9}[.)][ \t]+(.+)$/;

// One pass over a line's inline syntax: link, then bold, then italic. The alternation is
// ordered so `**a**` can never be read as an empty italic wrapping `*a*`.
const INLINE = /\[([^\]\n]*)\]\(([^()\s]+)\)|\*\*([^*\n]+?)\*\*|\*([^*\n]+?)\*/g;

// http/https ONLY. A `javascript:`/`data:` target is not "a link we decline to make
// clickable" -- it is rendered as the literal markdown source, so the reader sees exactly
// what the brief said and nothing is hidden behind a label.
const SAFE_HREF = /^https?:\/\//i;

function inlineSpans(line) {
  const out = [];
  const push = (s) => {
    if (!s) return;
    const last = out[out.length - 1];
    if (last && last.t === "text") last.v += s;      // keep runs of text in one span
    else out.push({ t: "text", v: s });
  };
  let at = 0;
  INLINE.lastIndex = 0;
  let m;
  while ((m = INLINE.exec(line)) !== null) {
    push(line.slice(at, m.index));
    at = INLINE.lastIndex;
    if (m[2] !== undefined) {                        // [label](href)
      if (SAFE_HREF.test(m[2])) out.push({ t: "a", v: m[1], href: m[2] });
      else push(m[0]);                               // unsafe scheme -> literal source
    } else if (m[3] !== undefined) {
      out.push({ t: "b", v: m[3] });
    } else {
      out.push({ t: "i", v: m[4] });
    }
  }
  push(line.slice(at));
  return out;
}

/**
 * @param {string} src  the contest description, as PixAI serves it
 * @returns {Array<object>} block structure (empty array for empty/absent input)
 */
export function parseMarkdownLite(src) {
  const text = String(src == null ? "" : src).replace(/\r\n?/g, "\n");
  const blocks = [];
  let para = null;        // {type:"p", spans:[...]} while lines keep arriving
  let list = null;        // {type:"ul"|"ol", items:[...]}

  const closeAll = () => { para = null; list = null; };

  for (const raw of text.split("\n")) {
    const line = raw.replace(/[ \t]+$/, "");
    if (!line.trim()) { closeAll(); continue; }      // a blank line ends every open block

    const h = HEADING.exec(line);
    if (h) {
      closeAll();
      blocks.push({ type: "h", level: h[1].length, spans: inlineSpans(h[2]) });
      continue;
    }

    const b = BULLET.exec(line);
    const o = b ? null : ORDERED.exec(line);
    if (b || o) {
      const kind = b ? "ul" : "ol";
      para = null;
      // A switch of list kind starts a new list rather than smuggling an <li> across.
      if (!list || list.type !== kind) { list = { type: kind, items: [] }; blocks.push(list); }
      list.items.push(inlineSpans((b || o)[1]));
      continue;
    }

    list = null;
    // A single newline inside a paragraph is a line break, not a new paragraph -- upstream
    // briefs use it for addresses and short stanza-ish runs.
    if (para) { para.spans.push({ t: "br" }); para.spans.push(...inlineSpans(line)); }
    else { para = { type: "p", spans: inlineSpans(line) }; blocks.push(para); }
  }
  return blocks;
}

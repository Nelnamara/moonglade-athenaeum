import { test, describe } from "node:test";
import assert from "node:assert/strict";

import { parseMarkdownLite } from "../../gallery/src/lib/markdownLite.js";

/* The contest brief's renderer (gallery/src/lib/markdownLite.js). PixAI serves a contest
   description as markdown and the detail view now renders it, so this pins the handful of
   constructs it claims to support -- and, more importantly, that everything else stays
   TEXT. There is no React harness here and none is needed: the module is a pure function
   returning plain data, which is exactly why it returns a structure instead of HTML. */

// the spans of the Nth block, flattened to a plain string (what a reader would see)
const flat = (spans) => spans.map((s) => (s.t === "br" ? "\n" : s.v)).join("");

describe("markdownLite -- blocks", () => {
  test("blank lines separate paragraphs; a single newline inside one is a break", () => {
    const b = parseMarkdownLite("first line\nsame paragraph\n\nsecond paragraph");
    assert.equal(b.length, 2);
    assert.equal(b[0].type, "p");
    assert.equal(flat(b[0].spans), "first line\nsame paragraph");
    assert.ok(b[0].spans.some((s) => s.t === "br"), "the single newline becomes a br span");
    assert.equal(flat(b[1].spans), "second paragraph");
  });

  test("the JoJo-style plain brief is exactly its paragraphs -- nothing invented", () => {
    // The live JoJo Pose description: four plain paragraphs, no markdown syntax at all.
    const jojo = [
      'From bold poses with the body dramatically arched backward, to sharp, confident'
        + ' pointing gestures, and even unique poses that make you wonder, "How is that'
        + ' pose even possible!?"',
      'Show us your idea of the coolest "JoJo pose"! Characters, outfits, and scenarios'
        + ' are completely up to you!',
      "Whether it's classic coolness, stylish, sexy, cute, or full-on comedic, feel free"
        + " to express your JoJo pose however you like.",
      '"This is the ultimate pose!" We can\'t wait to see your masterpiece! Let\'s all'
        + ' enjoy striking and wonderfully unique JoJo poses together!',
    ].join("\n\n");
    const b = parseMarkdownLite(jojo);
    assert.equal(b.length, 4);
    assert.ok(b.every((x) => x.type === "p"));
    // one text span each -- no stray emphasis conjured out of the apostrophes and quotes
    assert.ok(b.every((x) => x.spans.length === 1 && x.spans[0].t === "text"));
    assert.equal(flat(b[0].spans).slice(0, 10), "From bold ");
  });

  test("# / ## / ### are headings, and the hashes never survive into the text", () => {
    const b = parseMarkdownLite("# One\n## Two\n### Three\n#### Four");
    assert.deepEqual(b.slice(0, 3).map((x) => [x.type, x.level, flat(x.spans)]),
      [["h", 1, "One"], ["h", 2, "Two"], ["h", 3, "Three"]]);
    // four hashes is not a heading this renderer claims -- it stays a paragraph, verbatim
    assert.equal(b[3].type, "p");
    assert.equal(flat(b[3].spans), "#### Four");
  });

  test("- and * make a bullet list; 1. makes an ordered one", () => {
    const b = parseMarkdownLite("- alpha\n* beta\n\n1. first\n2. second");
    assert.equal(b[0].type, "ul");
    assert.deepEqual(b[0].items.map(flat), ["alpha", "beta"]);
    assert.equal(b[1].type, "ol");
    assert.deepEqual(b[1].items.map(flat), ["first", "second"]);
  });

  test("a list kind change starts a new list rather than mixing items", () => {
    const b = parseMarkdownLite("- a\n1. b");
    assert.deepEqual(b.map((x) => x.type), ["ul", "ol"]);
  });

  test("empty, blank and absent input all give no blocks (never a stray paragraph)", () => {
    for (const v of ["", "   \n\n  \n", null, undefined]) {
      assert.deepEqual(parseMarkdownLite(v), []);
    }
  });
});

describe("markdownLite -- inline", () => {
  test("**bold** and *italic* become their own spans", () => {
    const [p] = parseMarkdownLite("plain **loud** and *soft* end");
    assert.deepEqual(p.spans, [
      { t: "text", v: "plain " },
      { t: "b", v: "loud" },
      { t: "text", v: " and " },
      { t: "i", v: "soft" },
      { t: "text", v: " end" },
    ]);
  });

  test("bold wins over italic -- **x** is never an empty italic around *x*", () => {
    const [p] = parseMarkdownLite("**x**");
    assert.deepEqual(p.spans, [{ t: "b", v: "x" }]);
  });

  test("an http/https link becomes a link span carrying its href", () => {
    const [p] = parseMarkdownLite("see [the rules](https://pixai.art/rules) first");
    assert.deepEqual(p.spans[1], { t: "a", v: "the rules", href: "https://pixai.art/rules" });
  });

  test("a non-http scheme is NOT a link -- it renders as its own literal source", () => {
    for (const bad of ["javascript:alert(1)", "data:text/html,x", "/relative"]) {
      const [p] = parseMarkdownLite("[click](" + bad + ")");
      assert.equal(p.spans.length, 1);
      assert.equal(p.spans[0].t, "text", bad + " must not become a link");
      assert.equal(p.spans[0].v, "[click](" + bad + ")");
    }
  });
});

describe("markdownLite -- everything else is TEXT", () => {
  test("a <script> in the brief is a text span, never a node", () => {
    const src = '<script>alert("x")</script> and <img src=x onerror=y>';
    const [p] = parseMarkdownLite(src);
    assert.equal(p.type, "p");
    assert.equal(p.spans.length, 1);
    assert.equal(p.spans[0].t, "text");
    assert.equal(p.spans[0].v, src, "the raw HTML survives as literal text, unchanged");
  });

  test("no block or span type outside the declared set is ever produced", () => {
    const blocks = parseMarkdownLite(
      "# H\n\ntext with <b>html</b> and **bold**\n\n- <i>item</i>\n\n1. [x](https://a.b)");
    const okBlock = new Set(["p", "h", "ul", "ol"]);
    const okSpan = new Set(["text", "b", "i", "a", "br"]);
    for (const b of blocks) {
      assert.ok(okBlock.has(b.type), "unexpected block type " + b.type);
      const spans = b.spans || b.items.flat();
      for (const s of spans) assert.ok(okSpan.has(s.t), "unexpected span type " + s.t);
    }
    // the inline HTML came through as text, with the real markdown still parsed around it
    assert.equal(flat(blocks[1].spans), "text with <b>html</b> and bold");
    assert.ok(blocks[1].spans.some((s) => s.t === "b" && s.v === "bold"));
  });
});
